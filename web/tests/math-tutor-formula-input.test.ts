import assert from "node:assert/strict";
import test from "node:test";
import { insertFormula } from "../features/math-tutor/lib/formula-input";

test("wraps the selected expression before applying a power or fraction", () => {
  assert.deepEqual(insertFormula("a+b=c", 0, 3, "^2"), { text: "(a+b)^2=c", cursor: 7 });
  assert.deepEqual(insertFormula("a+b", 0, 3, "/"), { text: "(a+b)/", cursor: 6 });
  assert.deepEqual(insertFormula("x=", 2, 2, "/"), { text: "x=()/()", cursor: 3 });
  assert.deepEqual(insertFormula("x", 1, 1, "/"), { text: "x/", cursor: 2 });
  assert.deepEqual(insertFormula("", 0, 0, "^2"), { text: "()^2", cursor: 1 });
});

test("places the caret inside brackets and immediately after a line break", () => {
  assert.deepEqual(insertFormula("2x", 1, 1, "()"), { text: "2()x", cursor: 2 });
  assert.deepEqual(insertFormula("2x=4", 4, 4, "\n"), { text: "2x=4\n", cursor: 5 });
  assert.deepEqual(insertFormula("x<4", 1, 2, "<="), { text: "x<=4", cursor: 3 });
});
