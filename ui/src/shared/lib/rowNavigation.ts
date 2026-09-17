import type { MouseEvent as ReactMouseEvent } from "react";

function isInteractiveTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  return Boolean(target.closest("a,button,input,select,textarea,[role='button']"));
}

export function handleRowNavigation(
  event: ReactMouseEvent<HTMLElement>,
  href: string,
  navigate: (to: string) => void,
) {
  if (isInteractiveTarget(event.target)) {
    return;
  }

  if (event.type === "auxclick") {
    if (event.button === 1) {
      event.preventDefault();
      window.open(href, "_blank", "noopener,noreferrer");
    }
    return;
  }

  if (event.button !== 0) {
    return;
  }

  if (event.metaKey || event.ctrlKey) {
    event.preventDefault();
    window.open(href, "_blank", "noopener,noreferrer");
    return;
  }

  navigate(href);
}
