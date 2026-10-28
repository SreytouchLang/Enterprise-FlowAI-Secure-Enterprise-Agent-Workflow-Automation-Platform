"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  FileText,
  Plus,
  Send,
  Sparkles,
  Square,
  UserRound,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  Agent,
  api,
  Citation,
  consumeEvents,
  Conversation,
  list,
  Message,
  Page,
  requestHeaders,
  responseError,
} from "@/lib/api";
import { Button } from "./ui/button";
import { Busy, Empty, ErrorState, Heading, Loading } from "./common";
import { Dialog } from "./ui/dialog";
import { MarkdownMessage } from "./markdown-message";
import { useToast } from "./providers";
export function Workspace() {
  const client = useQueryClient();
  const toast = useToast();
  const agents = useQuery({
    queryKey: ["agents"],
    queryFn: () => api<Page<Agent>>("/agents"),
  });
  const conversations = useQuery({
    queryKey: ["conversations"],
    queryFn: () => api<Page<Conversation>>("/conversations"),
  });
  const [agentId, setAgentId] = useState("");
  const [conversationId, setConversationId] = useState("");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [status, setStatus] = useState("");
  const [streamError, setStreamError] = useState<Error | null>(null);
  const [citation, setCitation] = useState<Citation | null>(null);
  const controller = useRef<AbortController | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const selectedAgent = agentId || list(agents.data)[0]?.id || "";
  const conversation = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => api<Conversation>(`/conversations/${conversationId}`),
    enabled: !!conversationId,
  });
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("agent");
    if (id) setAgentId(id);
  }, []);
  useEffect(() => {
    if (conversation.data && !streaming && !streamError)
      setMessages(conversation.data.messages || []);
  }, [conversation.data, streaming, streamError]);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages, status]);
  useEffect(() => () => controller.current?.abort(), []);
  function newConversation() {
    if (streaming) return;
    setConversationId("");
    setMessages([]);
    setStreamError(null);
    setStatus("");
  }
  async function send(event?: React.FormEvent) {
    event?.preventDefault();
    if (!input.trim() || !selectedAgent || streaming || controller.current)
      return;
    const content = input.trim();
    setInput("");
    setStreamError(null);
    setStreaming(true);
    setStatus("Retrieving authorized knowledge…");
    const localId = `stream-${Date.now()}`;
    setMessages((old) => [
      ...old,
      { id: `user-${Date.now()}`, role: "user", content },
      { id: localId, role: "assistant", content: "" },
    ]);
    const requestController = new AbortController();
    controller.current = requestController;
    let terminal = false;
    try {
      let id = conversationId;
      if (!id) {
        const created = await api<Conversation>("/conversations", {
          method: "POST",
          body: { agent_id: selectedAgent, title: content.slice(0, 100) },
          signal: requestController.signal,
        });
        requestController.signal.throwIfAborted();
        id = created.id;
        setConversationId(id);
        client.invalidateQueries({ queryKey: ["conversations"] });
      }
      const response = await fetch(`/api/v1/conversations/${id}/messages`, {
        method: "POST",
        credentials: "include",
        headers: requestHeaders({ content }, "POST"),
        body: JSON.stringify({ content }),
        signal: requestController.signal,
      });
      requestController.signal.throwIfAborted();
      if (!response.ok) throw await responseError(response);
      if (!response.body)
        throw new Error("The response stream was unavailable.");
      await consumeEvents(response.body, ({ event, data }) => {
        if (event === "delta") {
          setStatus("");
          setMessages((old) =>
            old.map((m) =>
              m.id === localId
                ? { ...m, content: m.content + String(data.content || "") }
                : m,
            ),
          );
        } else if (event === "tool") {
          setStatus(
            `${String(data.name || "Tool")}: ${String(data.status || "working")}`,
          );
        } else if (event === "done") {
          terminal = true;
          setStatus("");
          setMessages((old) =>
            old.map((m) =>
              m.id === localId
                ? {
                    ...m,
                    id: String(data.message_id || m.id),
                    citations: (data.citations || []) as Citation[],
                  }
                : m,
            ),
          );
        } else if (event === "error") {
          terminal = true;
          throw new Error(
            String(
              data.message ||
                "The AI provider could not complete your request.",
            ),
          );
        }
      });
      if (!terminal)
        throw new Error(
          "The connection ended before the response completed. Your request may be incomplete.",
        );
      await client.invalidateQueries({ queryKey: ["conversation", id] });
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        setStreamError(
          new Error("Response stopped. Partial output may be incomplete."),
        );
      } else {
        const e =
          error instanceof Error ? error : new Error("Unable to send message.");
        setStreamError(e);
        toast(e.message, true);
      }
    } finally {
      requestController.abort();
      setStreaming(false);
      setStatus("");
      if (controller.current === requestController) controller.current = null;
    }
  }
  return (
    <>
      <Heading
        title="AI workspace"
        description="Ask questions, explore your knowledge, and work with your department’s AI team."
      />
      {agents.error ? (
        <ErrorState error={agents.error} />
      ) : agents.isPending ? (
        <Loading />
      ) : !list(agents.data).length ? (
        <div className="panel">
          <Empty
            title="No agents available"
            description="Ask your department administrator to configure an agent for your workspace."
          />
        </div>
      ) : (
        <div className="panel chat-layout">
          <aside className="conversation-list">
            <Button
              variant="outline"
              onClick={newConversation}
              disabled={streaming}
            >
              <Plus size={15} />
              New conversation
            </Button>
            {conversations.error ? (
              <ErrorState error={conversations.error} />
            ) : (
              list(conversations.data).map((c) => (
                <button
                  key={c.id}
                  disabled={streaming}
                  className={`conversation-item ${c.id === conversationId ? "active" : ""}`}
                  onClick={() => {
                    setConversationId(c.id);
                    setAgentId(c.agent_id);
                    setStreamError(null);
                  }}
                >
                  {c.title || "Untitled conversation"}
                </button>
              ))
            )}
          </aside>
          <section className="chat-main">
            <div className="chat-header">
              <div className="inline-actions">
                <Bot size={20} />
                <select
                  aria-label="Select AI agent"
                  value={selectedAgent}
                  disabled={streaming || !!conversationId}
                  onChange={(e) => setAgentId(e.target.value)}
                >
                  {list(agents.data).map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
              </div>
              <span className="text-muted">Grounded in authorized sources</span>
            </div>
            <div
              className="chat-messages"
              aria-live="polite"
              aria-busy={streaming}
            >
              {conversation.isFetching && !messages.length ? (
                <Loading />
              ) : conversation.error ? (
                <ErrorState error={conversation.error} />
              ) : messages.length ? (
                messages.map((m) => (
                  <div key={m.id} className={`chat-message ${m.role}`}>
                    <span className="chat-message-avatar">
                      {m.role === "user" ? (
                        <UserRound size={15} />
                      ) : (
                        <Sparkles size={16} />
                      )}
                    </span>
                    <div>
                      <h3>{m.role === "user" ? "You" : "AI assistant"}</h3>
                      <div className="chat-bubble">
                        {m.content ? (
                          m.role === "assistant" ? (
                            <MarkdownMessage content={m.content} />
                          ) : (
                            m.content
                          )
                        ) : streaming ? (
                          <Busy>Preparing an answer…</Busy>
                        ) : (
                          "No response content was received."
                        )}
                      </div>
                      {!!m.citations?.length && (
                        <div className="citation-list">
                          {m.citations.map((c, i) => (
                            <button
                              key={`${c.chunk_id}-${i}`}
                              className="citation"
                              onClick={() => setCitation(c)}
                            >
                              <FileText size={12} />
                              {i + 1}. {c.document_name}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))
              ) : (
                <div className="chat-intro">
                  <span className="icon-tile">
                    <Sparkles size={25} />
                  </span>
                  <h2>What can we work on?</h2>
                  <p>
                    Your assistant searches the knowledge you’re authorized to
                    access and links its answers to source documents.
                  </p>
                  <div className="chat-suggestions">
                    {[
                      "What do our policies say about approvals?",
                      "Summarize the documents available to my department.",
                    ].map((s) => (
                      <button key={s} onClick={() => setInput(s)}>
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {status && (
                <div className="stream-status">
                  <Busy>{status}</Busy>
                </div>
              )}
              {streamError && <ErrorState error={streamError} />}
              <div ref={end} />
            </div>
            <form className="chat-compose" onSubmit={send}>
              <div>
                <textarea
                  aria-label="Message your assistant"
                  placeholder="Ask your department assistant…"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      send();
                    }
                  }}
                  rows={2}
                  maxLength={8000}
                  disabled={streaming}
                />
                {streaming ? (
                  <Button
                    type="button"
                    variant="outline"
                    aria-label="Stop response"
                    onClick={() => controller.current?.abort()}
                  >
                    <Square size={16} />
                  </Button>
                ) : (
                  <Button
                    type="submit"
                    aria-label="Send message"
                    disabled={!input.trim() || !selectedAgent}
                  >
                    <Send size={17} />
                  </Button>
                )}
              </div>
              <small>
                AI output may contain errors. Review sources before making
                decisions. Enter to send · Shift + Enter for a new line.
              </small>
            </form>
          </section>
        </div>
      )}
      <Dialog
        open={!!citation}
        onOpenChange={() => setCitation(null)}
        title={citation?.document_name || "Source citation"}
        description={citation?.location || "Retrieved source excerpt"}
      >
        <p className="prose-text document-preview">{citation?.excerpt}</p>
        {citation && (
          <div className="form-actions">
            <Button asChild variant="outline">
              <a
                href={`/api/v1/documents/${citation.document_id}/download`}
                target="_blank"
                rel="noreferrer"
              >
                Open source document
              </a>
            </Button>
          </div>
        )}
      </Dialog>
    </>
  );
}
