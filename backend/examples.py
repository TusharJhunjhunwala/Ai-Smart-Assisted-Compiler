from typing import Dict, List

SAMPLE_PROGRAMS: List[Dict[str, str]] = [
    {
        "id": "valid_program",
        "title": "Valid Program (C++ cout)",
        "description": "Standard C++ stream output computation using cout << and endl.",
        "language": "cpp",
        "code": """int a = 10;
int b = 20;
int result = a + b;
cout << result << endl;"""
    },
    {
        "id": "c_printf_program",
        "title": "C Program (printf)",
        "description": "Standard ANSI C code using printf.",
        "language": "c",
        "code": """int width = 8;
int height = 12;
int area = width * height;
printf("Area is: %d\\n", area);"""
    },
    {
        "id": "typo_suggestion",
        "title": "AI Typo Suggestion",
        "description": "Contains an undeclared typo variable 'totl' which is resolved via Levenshtein distance to 'total'.",
        "language": "cpp",
        "code": """int total = 100;
totl = total + 20;
cout << total << endl;"""
    },
    {
        "id": "errors_and_opt",
        "title": "Errors + Optimizations",
        "description": "Comprehensive test suite: dead stores, missing semicolons, duplicate declarations, constant folding, and common subexpressions.",
        "language": "cpp",
        "code": """#include <iostream>
using namespace std;

int add(int a, int b) {
    int unused = 100;

    int x = 10 + 20;
    int y = x + 5;
    int z = y * 1;
    int p = z * 2;

    int a1 = x + y;
    int a2 = x + y;

    int copy = x;

    int overwrite = 10;
    overwrite = 20;

    int zero1 = x * 0;
    int zero2 = 0 * y;
    int same = z + 0;

    totl = total + 20;

    int missing = x + 5

    int duplicate = 10;
    int duplicate = 20;

    int result = addd(x, y);

    cout << result << endl;

    return 0;
}"""
    },
    {
        "id": "functions_and_calls",
        "title": "Functions & Autocomplete Demo",
        "description": "Ideal for testing AI autocomplete: type 'void add() {' or function calls.",
        "language": "cpp",
        "code": """#include <iostream>
using namespace std;

int multiply(int a, int b) {
    int res = a * b;
    return res;
}

int main() {
    int num1 = 15;
    int num2 = 30;
    int total = multiply(num1, num2);
    cout << "Total: " << total << endl;
    return 0;
}"""
    },
    {
        "id": "loops_and_conditionals",
        "title": "Loops & Conditionals",
        "description": "Demonstrates for loops, while loops, and if-condition checks with expressions.",
        "language": "cpp",
        "code": """int counter = 0;
int limit = 10;

for (int i = 0; i < limit; i++) {
    counter = counter + i;
}

if (counter > 20) {
    cout << "Counter: " << counter << endl;
}"""
    }
]
