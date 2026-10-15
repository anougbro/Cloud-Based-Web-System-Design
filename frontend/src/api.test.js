import { describe, expect, it } from "vitest";
import { ApiError, CURRENCY, money } from "./api.js";

// Mirrors the backend rule in `domain.py`: a payment the user already rounded
// generates nothing. The frontend renders the value the backend computed, but
// a formatting error here would silently misstate every amount on screen, so
// the boundary is pinned.
describe("money", () => {
  it("renders cents as a two-decimal euro amount", () => {
    expect(money(0)).toBe(`${CURRENCY}0,00`);
    expect(money(5)).toBe(`${CURRENCY}0,05`);
    expect(money(50)).toBe(`${CURRENCY}0,50`);
    expect(money(1250)).toBe(`${CURRENCY}12,50`);
    expect(money(1138940)).toBe(`${CURRENCY}11389,40`);
  });

  it("uses a comma as the decimal separator", () => {
    // French locale formatting is intentional and must not drift to "12.50",
    // which would read as twelve euros fifty in this UI.
    expect(money(1234)).toBe(`${CURRENCY}12,34`);
  });

  it("treats a missing value as zero rather than NaN", () => {
    // The dashboard renders "—" while loading, but any null slipping through
    // would otherwise render "NaN" on a financial screen.
    expect(money(null)).toBe(`${CURRENCY}0,00`);
    expect(money(undefined)).toBe(`${CURRENCY}0,00`);
  });

  it("never loses a cent to floating point error", () => {
    // 0.1 + 0.2 != 0.3 in IEEE 754. Integer cents must not inherit that.
    expect(money(10 + 20)).toBe(`${CURRENCY}0,30`);
    expect(money(1138940 + 50)).toBe(`${CURRENCY}11389,90`);
  });

  it("round-trips an amount through display and back", () => {
    const original = 987654;
    const displayed = money(original);
    const [whole, cents] = displayed.replace(CURRENCY, "").replace(",", ".").split(".");
    expect(Number(whole) * 100 + Number(cents)).toBe(original);
  });
});

describe("ApiError", () => {
  it("defaults to status 0 for network failures", () => {
    const err = new ApiError("boom");
    expect(err.status).toBe(0);
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe("ApiError");
  });

  it("carries extra fields such as retryAfter", () => {
    const err = new ApiError("Too many requests.", 429, { retryAfter: "30" });
    expect(err.status).toBe(429);
    expect(err.retryAfter).toBe("30");
  });
});
