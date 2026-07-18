cmake_minimum_required(VERSION 3.20)
project(autorotation_optimizer LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(NLopt REQUIRED)

add_executable(autorotation_opt
    src/main.cpp
    src/aero_client.cpp
    src/rotor_model.cpp
)

target_include_directories(autorotation_opt PRIVATE include)
target_link_libraries(autorotation_opt PRIVATE NLopt::nlopt)

target_compile_options(autorotation_opt PRIVATE -Wall -Wextra -Wpedantic)
