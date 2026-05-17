#include <iostream>

int main() {
    int* bad_pointer = new int[50]; // Allocate memory
    bad_pointer[0] = 42;            // USE the variable so the compiler is happy!
    
    int num;
    if (std::cin >> num) {
        std::cout << num * 2 << "\n";
    }
    
    // We still forgot to do: delete[] bad_pointer;
    return 0; 
}