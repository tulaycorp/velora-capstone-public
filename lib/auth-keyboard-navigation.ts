export type AuthFocusDirection = "forward" | "backward";

export function getAdjacentAuthFocusTarget<T>(
  targets: readonly T[],
  currentTarget: T,
  direction: AuthFocusDirection,
  preferredTarget?: T | null
) {
  if (
    preferredTarget !== null &&
    preferredTarget !== undefined &&
    targets.includes(preferredTarget)
  ) {
    return preferredTarget;
  }

  const currentIndex = targets.indexOf(currentTarget);
  if (currentIndex === -1) {
    return null;
  }

  const nextIndex = currentIndex + (direction === "forward" ? 1 : -1);
  return targets[nextIndex] ?? null;
}
