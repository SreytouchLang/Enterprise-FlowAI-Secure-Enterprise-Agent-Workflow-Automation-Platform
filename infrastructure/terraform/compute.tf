resource "aws_ecr_repository" "application" {
  for_each             = toset(["api", "web"])
  name                 = "${local.name}-${each.key}"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "AES256" }
}
resource "aws_ecr_lifecycle_policy" "application" {
  for_each   = aws_ecr_repository.application
  repository = each.value.name
  policy     = jsonencode({ rules = [{ rulePriority = 1, description = "Expire old untagged layers", selection = { tagStatus = "untagged", countType = "sinceImagePushed", countUnit = "days", countNumber = 14 }, action = { type = "expire" } }] })
}
resource "aws_ecs_cluster" "main" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}
resource "aws_cloudwatch_log_group" "application" {
  for_each          = toset(["api", "worker", "web", "scheduler", "migration"])
  name              = "/ecs/${local.name}/${each.key}"
  retention_in_days = var.log_retention_days
}
locals {
  services = {
    api       = { image = var.api_image, port = 8000, command = [], cpu = 512, memory = 1024 }
    worker    = { image = var.api_image, port = 0, command = ["celery", "-A", "app.worker.celery_app", "worker", "--loglevel=INFO", "--concurrency=2"], cpu = 1024, memory = 2048 }
    scheduler = { image = var.api_image, port = 0, command = ["celery", "-A", "app.worker.celery_app", "beat", "--loglevel=INFO", "--schedule=/tmp/enterpriseflow-beat"], cpu = 256, memory = 512 }
    web       = { image = var.web_image, port = 3000, command = [], cpu = 256, memory = 512 }
  }
  application_environment = [
    { name = "APP_ENV", value = var.environment },
    { name = "REQUIRE_VIRUS_SCAN", value = "true" },
    { name = "CLAMAV_HOST", value = var.clamav_host },
    { name = "ENABLE_DEV_USERS", value = "false" },
    { name = "ENABLE_FAKE_PROVIDER", value = "false" },
    { name = "JOBS_EAGER", value = "false" },
    { name = "STORAGE_BACKEND", value = "s3" },
    { name = "S3_BUCKET", value = aws_s3_bucket.documents.id },
    { name = "S3_REGION", value = var.region },
    { name = "OIDC_ISSUER", value = var.oidc_issuer },
    { name = "OIDC_CLIENT_ID", value = var.oidc_client_id },
    { name = "OIDC_AUDIENCE", value = var.oidc_audience },
    { name = "FRONTEND_URL", value = "https://${var.app_domain}" },
    { name = "API_PUBLIC_URL", value = "https://${var.app_domain}" },
    { name = "ALLOWED_ORIGINS", value = "https://${var.app_domain}" }
  ]
}
resource "aws_ecs_task_definition" "application" {
  for_each                 = local.services
  family                   = "${local.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = contains(["web", "scheduler"], each.key) ? aws_iam_role.web.arn : aws_iam_role.application.arn
  container_definitions = jsonencode([merge({
    name                                          = each.key, image = each.value.image, essential = true, user = each.key == "web" ? "1000" : "10001",
    portMappings                                  = each.value.port == 0 ? [] : [{ containerPort = each.value.port, protocol = "tcp" }],
    environment                                   = each.key == "web" ? [{ name = "API_INTERNAL_URL", value = "https://${var.app_domain}" }] : local.application_environment,
    secrets                                       = each.key == "web" ? [] : [for key in ["DATABASE_URL", "REDIS_URL", "SESSION_COOKIE_SECRET", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"] : { name = key, valueFrom = "${aws_secretsmanager_secret.runtime.arn}:${key}::" }],
    linuxParameters                               = { initProcessEnabled = true },
    logConfiguration                              = { logDriver = "awslogs", options = { "awslogs-group" = aws_cloudwatch_log_group.application[each.key].name, "awslogs-region" = var.region, "awslogs-stream-prefix" = each.key } }
    }, length(each.value.command) > 0 ? { command = each.value.command } : {}, each.key == "api" ? {
    healthCheck                                   = { command = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live')\""], interval = 30, timeout = 5, retries = 3, startPeriod = 60 }
    } : each.key == "worker" ? {
    healthCheck = { command = ["CMD-SHELL", "celery -A app.worker.celery_app inspect ping -d celery@$HOSTNAME --timeout=5"], interval = 60, timeout = 10, retries = 3, startPeriod = 60 }
  } : {})])
}
resource "aws_ecs_task_definition" "migration" {
  family                   = "${local.name}-migration"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.migration_execution.arn
  task_role_arn            = aws_iam_role.web.arn
  container_definitions = jsonencode([{
    name             = "migration", image = var.api_image, essential = true, user = "10001",
    command          = ["sh", "-c", "python bootstrap_database.py && alembic upgrade head"],
    environment      = local.application_environment,
    secrets          = [for key in ["DATABASE_URL", "MIGRATION_DATABASE_URL", "SESSION_COOKIE_SECRET"] : { name = key, valueFrom = "${aws_secretsmanager_secret.migration.arn}:${key}::" }],
    logConfiguration = { logDriver = "awslogs", options = { "awslogs-group" = aws_cloudwatch_log_group.application["migration"].name, "awslogs-region" = var.region, "awslogs-stream-prefix" = "migration" } }
  }])
}
resource "aws_ecs_service" "application" {
  for_each                           = local.services
  name                               = "${local.name}-${each.key}"
  cluster                            = aws_ecs_cluster.main.id
  task_definition                    = aws_ecs_task_definition.application[each.key].arn
  desired_count                      = each.key == "scheduler" && var.desired_count > 0 ? 1 : var.desired_count
  launch_type                        = "FARGATE"
  platform_version                   = "1.4.0"
  health_check_grace_period_seconds  = contains(["worker", "scheduler"], each.key) ? null : 90
  deployment_minimum_healthy_percent = each.key == "scheduler" ? 0 : 100
  deployment_maximum_percent         = each.key == "scheduler" ? 100 : 200
  enable_execute_command             = false
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }
  dynamic "load_balancer" {
    for_each = contains(["worker", "scheduler"], each.key) ? [] : [each.key]
    content {
      target_group_arn = aws_lb_target_group.application[load_balancer.value].arn
      container_name   = load_balancer.value
      container_port   = each.value.port
    }
  }
  lifecycle { ignore_changes = [task_definition, desired_count] }
  depends_on = [aws_lb_listener.https, aws_lb_listener_rule.api, aws_iam_role_policy_attachment.execution]
}
resource "aws_appautoscaling_target" "service" {
  for_each           = { for key, service in local.services : key => service if key != "scheduler" }
  min_capacity       = var.desired_count
  max_capacity       = 10
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.application[each.key].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}
resource "aws_appautoscaling_policy" "cpu" {
  for_each           = { for key, service in local.services : key => service if key != "scheduler" }
  name               = "${local.name}-${each.key}-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.service[each.key].resource_id
  scalable_dimension = aws_appautoscaling_target.service[each.key].scalable_dimension
  service_namespace  = "ecs"
  target_tracking_scaling_policy_configuration {
    target_value       = 65
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
    predefined_metric_specification { predefined_metric_type = "ECSServiceAverageCPUUtilization" }
  }
}
