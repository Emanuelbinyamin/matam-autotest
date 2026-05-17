CXX = g++
CXXFLAGS = -std=c++17 -Wall -pedantic-errors -Werror -g
OBJS = main.o math.o
EXEC = main

$(EXEC): $(OBJS)
	$(CXX) $(CXXFLAGS) $(OBJS) -o $(EXEC)

main.o: main.cpp math.h
	$(CXX) $(CXXFLAGS) -c main.cpp

math.o: math.cpp math.h
	$(CXX) $(CXXFLAGS) -c math.cpp

clean:
	rm -f $(OBJS) $(EXEC)
