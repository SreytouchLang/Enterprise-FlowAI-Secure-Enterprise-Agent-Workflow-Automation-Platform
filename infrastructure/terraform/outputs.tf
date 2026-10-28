output "alb_dns_name" { value = aws_lb.main.dns_name }
output "application_url" { value = "https://${var.app_domain}" }
output "cluster_name" { value = aws_ecs_cluster.main.name }
output "private_subnet_ids" { value = aws_subnet.private[*].id }
output "task_security_group_id" { value = aws_security_group.tasks.id }
output "ecr_repositories" { value = { for key, repo in aws_ecr_repository.application : key => repo.repository_url } }
output "runtime_secret_arn" { value = aws_secretsmanager_secret.runtime.arn }
output "migration_secret_arn" { value = aws_secretsmanager_secret.migration.arn }
output "database_master_secret_arn" {
  value     = aws_db_instance.main.master_user_secret[0].secret_arn
  sensitive = true
}
output "database_endpoint" { value = aws_db_instance.main.address }
output "redis_endpoint" { value = aws_elasticache_replication_group.main.primary_endpoint_address }
output "documents_bucket" { value = aws_s3_bucket.documents.id }
output "deploy_role_arn" { value = aws_iam_role.deploy.arn }
output "task_definition_families" { value = { for key, task in aws_ecs_task_definition.application : key => task.family } }
output "migration_task_family" { value = aws_ecs_task_definition.migration.family }
