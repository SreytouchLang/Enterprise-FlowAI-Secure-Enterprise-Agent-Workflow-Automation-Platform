"use client";
export default function ErrorPage({
  reset,
}: {
  error: Error;
  reset: () => void;
}) {
  return (
    <div className="empty" role="alert">
      <h2>This page couldn’t be displayed</h2>
      <p>An unexpected error occurred. Try loading the page again.</p>
      <button className="button button-primary" onClick={reset}>
        Try again
      </button>
    </div>
  );
}
