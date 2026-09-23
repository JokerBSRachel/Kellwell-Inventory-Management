// Shared integer-based decimal math helpers.
//
// Browsers do floating-point (IEEE-754) arithmetic, which can land exactly on
// a rounding boundary (e.g. an exact .xx5) and round the "wrong" way, or drift
// from what Python's Decimal computes for the same inputs server-side. Any
// value here that's constrained to 2 decimal places (currency, quantities,
// recipe amounts — anywhere the input uses step="0.01") can be multiplied
// exactly by first converting to an integer count of hundredths, doing the
// multiplication in integer space, and rounding only once, at the very end.
//
// The names below ("Cents"/"TenThousandths") come from this file's original
// use on the inventory sheet's price × quantity math, but the same integer
// technique applies to any 2-decimal-place values — e.g. recipe ingredient
// scaling reuses these functions even though nothing there is currency.

function parseNum(input) {
    // Reads a numeric value out of a DOM input element, defensively —
    // missing element or unparseable value both fall back to 0.
    if (!input) return 0;
    const val = parseFloat(input.value);
    return isNaN(val) ? 0 : val;
}

function toCents(value) {
    // Converts a plain decimal number into an integer count of hundredths,
    // correcting any tiny floating-point representation drift.
    return Math.round(value * 100);
}

function tenThousandthsProduct(aVal, bVal) {
    // Both inputs are constrained to 2 decimal places, so their exact
    // product can be computed entirely in integers, in units of 1/10000 —
    // this sidesteps IEEE-754 floating-point drift completely, matching the
    // exactness Python's Decimal arithmetic already gives server-side.
    const aCents = toCents(aVal);
    const bCents = toCents(bVal);
    return aCents * bCents;
}

function roundTenThousandthsToCents(tenThousandths) {
    // Round-half-up to the nearest hundredth, using only integer arithmetic —
    // this is the ONE place actual rounding happens; everything upstream
    // stays in exact, unrounded ten-thousandths so summing many values never
    // drifts from "sum exact, round once" (matches Excel and the server).
    const remainder = tenThousandths % 100;
    return (tenThousandths - remainder) / 100 + (remainder * 2 >= 100 ? 1 : 0);
}