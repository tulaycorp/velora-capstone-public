"use client";

import { getAdjacentAuthFocusTarget } from "@/lib/auth-keyboard-navigation";
import { cn } from "@/lib/utils";

const focusableSelector = [
  "a[href]",
  "button:not(:disabled)",
  "input:not(:disabled):not([type='hidden'])",
  "select:not(:disabled)",
  "textarea:not(:disabled)",
  "[contenteditable='true']",
  "[tabindex]:not([tabindex='-1'])"
].join(",");

function isKeyboardVisible(element: HTMLElement) {
  const isAuthField = element instanceof HTMLInputElement && element.type !== "hidden";

  if (
    element.hidden ||
    (element.tabIndex < 0 && !isAuthField) ||
    element.closest("[aria-hidden='true'], [inert]")
  ) {
    return false;
  }

  const style = window.getComputedStyle(element);
  return (
    style.display !== "none" &&
    style.visibility !== "hidden" &&
    style.opacity !== "0" &&
    element.getClientRects().length > 0
  );
}

function isIdentifierInput(element: HTMLElement): element is HTMLInputElement {
  if (!(element instanceof HTMLInputElement)) {
    return false;
  }

  const autocomplete = element.autocomplete.toLowerCase();
  const name = element.name.toLowerCase();
  return (
    element.type === "email" ||
    autocomplete === "email" ||
    autocomplete === "username" ||
    name === "email" ||
    name === "emailaddress" ||
    name === "identifier"
  );
}

function isPasswordInput(element: HTMLElement): element is HTMLInputElement {
  if (!(element instanceof HTMLInputElement)) {
    return false;
  }

  const autocomplete = element.autocomplete.toLowerCase();
  return (
    element.type === "password" ||
    autocomplete === "current-password" ||
    autocomplete === "new-password"
  );
}

function getPreferredFieldTarget(
  scope: HTMLElement,
  currentTarget: HTMLElement,
  direction: "forward" | "backward"
) {
  const fields = Array.from(scope.querySelectorAll<HTMLElement>("input")).filter(
    isKeyboardVisible
  );
  const identifiers = fields.filter(isIdentifierInput);
  const passwords = fields.filter(isPasswordInput);

  if (direction === "forward" && isIdentifierInput(currentTarget)) {
    return passwords[0] ?? null;
  }

  if (
    direction === "backward" &&
    isPasswordInput(currentTarget) &&
    passwords[0] === currentTarget
  ) {
    return identifiers.at(-1) ?? null;
  }

  return null;
}

function getVisibleFocusableElements() {
  return Array.from(document.querySelectorAll<HTMLElement>(focusableSelector)).filter(
    isKeyboardVisible
  );
}

export function AuthKeyboardScope({
  className,
  children
}: {
  className?: string;
  children: React.ReactNode;
}) {
  function handleKeyDownCapture(event: React.KeyboardEvent<HTMLDivElement>) {
    if (
      event.key !== "Tab" ||
      event.altKey ||
      event.ctrlKey ||
      event.metaKey ||
      event.defaultPrevented ||
      !(event.target instanceof HTMLElement)
    ) {
      return;
    }

    const direction = event.shiftKey ? "backward" : "forward";
    const focusableElements = getVisibleFocusableElements();
    const nextTarget = getAdjacentAuthFocusTarget(
      focusableElements,
      event.target,
      direction,
      getPreferredFieldTarget(event.currentTarget, event.target, direction)
    );

    if (!nextTarget) {
      return;
    }

    event.stopPropagation();
    event.preventDefault();
    nextTarget.focus();
  }

  return (
    <div
      data-auth-keyboard-scope
      className={cn(className)}
      onKeyDownCapture={handleKeyDownCapture}
    >
      {children}
    </div>
  );
}
