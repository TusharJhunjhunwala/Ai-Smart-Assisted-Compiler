from typing import Dict, List

# Five demos, each built to show one part of the platform.
# Load one from the "Demos" menu and click Run / Analyze.

SAMPLE_PROGRAMS: List[Dict[str, str]] = [
    {
        "id": "tour_clean_program",
        "title": "1. Tour: Output, Tokens & Ghost Text",
        "description": "A correct program: see its output, token stream and symbol table, then try AI Ghost Text.",
        "language": "cpp",
        "code": """// DEMO 1 - A correct program
// Click Run / Analyze, then open each tab:
//   Program Output - the real output, compiled with g++
//   Tokens         - every keyword, identifier, operator and literal
//   Symbol Table   - each variable with its type, value and line
//
// Try AI Ghost Text: on the empty line at the bottom of this file, type
//     int factorial(int n) {
// wait a moment for the grey suggestion, then press Tab to accept it.
// (Alt + ] shows the next suggestion, Esc dismisses it.)

#include <iostream>
using namespace std;

int square(int x) {
    return x * x;
}

int main() {
    int count = 5;
    int total = 0;

    for (int i = 1; i <= count; i++) {
        total = total + square(i);
    }

    cout << "Sum of squares 1.." << count << " = " << total << endl;

    if (total > 50) {
        cout << "That is more than 50" << endl;
    }
    return 0;
}

"""
    },
    {
        "id": "syntax_errors",
        "title": "2. Syntax Errors -> Fix All",
        "description": "Ten classic typing mistakes. Fix them one by one with Apply Fix, or all at once with Fix All Errors.",
        "language": "cpp",
        "code": """// DEMO 2 - Classic beginner mistakes
// Click Run / Analyze: the Diagnostics tab lists every error with its line.
// Then either:
//   - click "Apply Fix" on one diagnostic to fix just that problem, or
//   - click "Fix All Errors" to review and apply every fix at once.
//
// Mistakes in this program:
//   Using namespace (capital U)   void main()           missing ;
//   Cout instead of cout          cout < (needs <<)     missing ')'
//   unclosed "string              x endl (missing <<)   retrun typo
//   missing closing '}'

#include <iostream>
Using namespace std;

void main() {
    int marks = 72
    int bonus = 5;

    Cout << "Welcome to SmartCompiler" << endl;
    cout < "Total marks: " << marks + bonus << endl;

    if ((marks + bonus) > 75 {
        cout << "Grade: A << endl;
    }
    cout << "Bonus added: " bonus endl;

    retrun 0;
"""
    },
    {
        "id": "smart_fixes",
        "title": "3. Smart Fixes",
        "description": "Errors that need real understanding: a missing parameter, a function used before it is defined, undeclared variables and a function written inside main.",
        "language": "cpp",
        "code": """// DEMO 3 - Fixes that need to understand the program
// Click Run / Analyze, then Fix All Errors, and read "What was fixed".
//
//  - isPrime() uses 'n' but has no parameter, and main calls isPrime(7)
//      -> Fix All makes it a parameter:  bool isPrime(int n)
//  - main calls cube() before cube() is defined
//      -> a declaration is added above main
//  - 'for (i = 0; ...)' never declares i        -> for (int i = 0; ...)
//  - 'evens = 0;' is never declared              -> int evens = 0;
//  - average() is written INSIDE main            -> moved above main

#include <iostream>
using namespace std;

bool isPrime() {
    if (n <= 1) return false;
    for (int d = 2; d * d <= n; d++) {
        if (n % d == 0) return false;
    }
    return true;
}

int main() {
    cout << "Is 7 prime? " << isPrime(7) << endl;
    cout << "Cube of 3: " << cube(3) << endl;

    evens = 0;
    for (i = 1; i <= 10; i++) {
        if (i % 2 == 0) evens++;
    }
    cout << "Even numbers from 1 to 10: " << evens << endl;

    double average(double a, double b) {
        return (a + b) / 2;
    }
    cout << "Average of 4 and 7: " << average(4, 7) << endl;
    return 0;
}

int cube(int x) {
    return x * x * x;
}
"""
    },
    {
        "id": "hidden_bugs",
        "title": "4. Hidden Bugs That Compile",
        "description": "Code that compiles but gives wrong answers: '=' instead of '==', a stray ';' after if, an uninitialised total and a missing return.",
        "language": "cpp",
        "code": """// DEMO 4 - Bugs a normal compiler lets through
// This program COMPILES, but every marked line gives a wrong result.
// Click Run / Analyze: see the wrong output, then the WARNINGS in Diagnostics.
// Fix All Errors repairs all of them - run again and compare the output.

#include <iostream>
using namespace std;

int grade(int score) {
    if (score >= 90) return 1;
    if (score >= 75) return 2;
    // BUG: no return value when score < 75
}

int main() {
    int sum;                        // BUG: never set to 0
    for (int i = 1; i <= 5; i++) {
        sum += i;
    }
    cout << "Sum 1..5 = " << sum << endl;

    int level = 3;
    if (level = 1) {                // BUG: '=' assigns, '==' compares
        cout << "Beginner" << endl;
    }

    int stock = 0;
    if (stock > 0); {               // BUG: the ';' ends the if
        cout << "In stock!" << endl;
    }

    cout << "Grade for 60: " << grade(60) << endl;
    return 0;
}
"""
    },
    {
        "id": "optimizer",
        "title": "5. Optimizer",
        "description": "A correct program full of optimisation opportunities: constant folding and propagation, algebraic simplification, strength reduction, common subexpressions, dead code.",
        "language": "cpp",
        "code": """// DEMO 5 - What an optimising compiler sees
// This program is correct. Click Run / Analyze and open:
//   Optimization - each optimisation found, with the line it applies to
//   Diagnostics  - unused variables and overwritten values (dead code)

#include <iostream>
using namespace std;

int twice(int value) {
    int result = value * 2;         // strength reduction: * 2 -> value + value
    int alias = result;             // copy propagation: alias is just result
    return alias;
}

int main() {
    int seconds = 60 * 60 * 24;     // constant folding: computed at compile time
    int days = 7;
    int week = seconds * days;      // constant propagation: both values are known

    int price = 250;
    int same = price * 1;           // algebraic simplification: * 1 does nothing
    int nothing = price * 0;        // algebraic simplification: always 0
    int doubled = twice(price);

    int a = 12;
    int b = 30;
    int first = a + b;
    int second = a + b;             // common subexpression: a + b computed twice

    int copy = first;               // propagation: first is known to be 42
    int unused = 999;               // dead code: never used

    int discount = 10;
    discount = 20;                  // the first value 10 is never read

    cout << week << " " << same << " " << nothing << " " << doubled << endl;
    cout << second << " " << copy << " " << discount << endl;
    return 0;
}
"""
    },
]
