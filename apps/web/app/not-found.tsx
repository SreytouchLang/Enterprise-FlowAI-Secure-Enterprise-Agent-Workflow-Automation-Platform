import Link from "next/link";
export default function NotFound() {
  return (
    <div className="empty">
      <h1>Page not found</h1>
      <p>This page isn’t part of your workspace.</p>
      <Link className="button button-primary" href="/">
        Return to overview
      </Link>
    </div>
  );
}
