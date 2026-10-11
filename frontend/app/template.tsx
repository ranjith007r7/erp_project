"use client";

/**
 * A template (unlike a layout) is mounted fresh on every navigation, so each page entrance plays
 * every time you switch module. The page fades and rises a few pixels, and the blocks inside it
 * (cards, forms, tables) follow one after another - see .page-enter in globals.css.
 * Reduced-motion visitors get the page instantly.
 */
export default function Template({ children }: { children: React.ReactNode }) {
  return <div className="page-enter">{children}</div>;
}
