#include <iostream>
#include "math.h"

int main() {
    int num;
    if (std::cin >> num) {
        std::cout << multiplyByTwo(num) << "\n";
    }
    return 0; 
}
