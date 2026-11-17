# Specification — Basic Version (MVP)

Project: **Real Analysis Homework Checker — Basic Version (MVP)**.
This is the original requirements document supplied by the project owner. The
implementation plan that satisfies it lives in
[ARCHITECTURE.md](ARCHITECTURE.md) and [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md).

## 1. Project Overview

Build an AI-powered real analysis homework checking tool for undergraduate
mathematics students.

The system should allow students to input:

1. A real analysis problem.
2. Their own mathematical proof or solution.

The system should then:

1. Understand the mathematical problem and the student's proof.
2. Convert the problem and proof into Lean 4 code.
3. Use Lean 4 and Mathlib to formally verify the generated proof.
4. If the proof is incorrect or cannot be verified, identify the likely error
   location and explain the reason in understandable language.

This is a software engineering project. The priority is to build a functional,
reliable, and testable application rather than train a new machine learning
model.

## 2. Target Users

Undergraduate mathematics students who are learning real analysis and may have
little or no experience with Lean. The interface should be simple, intuitive,
and suitable for beginners.

## 3. Core Features

### Feature A: Student Input

Provide a simple web interface where students can enter:

* Problem statement.
* Their proposed solution or proof.

For the initial version, support text input and standard mathematical notation.
Do not implement handwritten image recognition yet.

### Feature B: Mathematical Understanding and Lean Translation

Use an LLM API to process the student's input. The model should:

1. Identify the assumptions and hypotheses in the problem.
2. Identify the mathematical statement that needs to be proved.
3. Extract the logical structure of the student's proof.
4. Translate the problem and proof into Lean 4 syntax using Mathlib.
5. Preserve the original mathematical meaning as accurately as possible.

The generated Lean code should be displayed to the user.

IMPORTANT:

* Do not silently change the original problem into an easier proposition.
* Clearly separate the original mathematical statement from its formalized Lean
  representation.
* If the problem is ambiguous or cannot be reliably formalized, ask the student
  for clarification instead of inventing assumptions.
* Do not claim that the student's original proof is correct merely because the
  generated Lean code compiles.

### Feature C: Lean Verification

Use an actual Lean 4 environment with Mathlib to check the generated code. The
application must execute Lean verification rather than rely on the LLM's
judgment.

Possible results:

1. **Verified:** Lean successfully checks the generated proof.
2. **Verification failed:** Lean reports an error or unresolved goal.
3. **Translation failed:** The LLM cannot reliably translate the input.
4. **Runtime error:** Lean execution or API communication failed.

Never fabricate a successful verification result.

### Feature D: Error Detection and Localization

If Lean verification fails, analyze the error information. Try to identify:

* The relevant line or proof step.
* The type of error.
* The likely reason.
* A brief explanation of what went wrong.
* A possible direction for correction.

Distinguish between:

1. Mathematical reasoning errors.
2. Missing assumptions or incomplete proofs.
3. Incorrect theorem application.
4. Algebraic or computational errors.
5. Lean syntax errors.
6. Type mismatches.
7. Unresolved proof goals.

If the exact mathematical error cannot be determined, explicitly state that the
system cannot confidently identify it. Do not confuse a Lean compilation error
with a mathematical reasoning error.

### Feature E: Result Display

Display the following information:

* Original problem.
* Student's original proof.
* Formalized Lean proposition.
* Generated Lean code.
* Verification result.
* Error location, if applicable.
* Explanation of the error.
* Suggested correction, if available.

Keep the interface clean and readable.

## 4. Technical Requirements

Preferred technologies:

* Python: main programming language.
* Streamlit: user interface.
* Lean 4 + Mathlib: formal verification.
* LLM API: mathematical interpretation and Lean code generation.
* Git: version control.

Use a modular architecture. Separate the following components:

1. User interface.
2. LLM communication.
3. Mathematical problem parsing.
4. Lean code generation.
5. Lean execution and verification.
6. Error analysis.
7. Result presentation.

Do not put the entire application into one Python file.

Use environment variables for API keys. Never hardcode API credentials.

Add appropriate error handling, execution timeouts, and logging.

Run Lean code in a controlled environment. Do not execute arbitrary
student-generated shell commands.

## 5. Development Instructions

Work incrementally. Before writing code:

1. Inspect the current project directory.
2. Explain the proposed architecture.
3. List the files that need to be created.
4. Identify technical risks and dependencies.

Then implement one module at a time. After each module:

1. Explain what was implemented.
2. Run relevant tests.
3. Report errors and limitations.
4. Do not claim success unless the feature has actually been tested.

Do not rewrite unrelated files without a clear reason.

## 6. Initial Scope Limitations

To ensure the project is achievable:

* Focus on undergraduate real analysis.
* Initially support a limited range of topics, such as sequences and
  convergence.
* Support typed mathematical input only.
* Do not train a custom LLM.
* Do not implement image recognition.
* Do not implement a complicated user account system.
* Do not attempt to explain every possible mathematical error.

Prioritize correctness and reliability over the number of features.

## 7. Expected Deliverable

A working web application in which a student can:

1. Enter a real analysis problem.
2. Enter their proposed proof.
3. Generate Lean 4 code.
4. Run actual Lean verification.
5. See whether the generated proof is accepted.
6. Receive an explanation of the detected error and its likely location if
   verification fails.

The result should be a demonstrable software prototype with a clear README,
installation instructions, and test cases.
