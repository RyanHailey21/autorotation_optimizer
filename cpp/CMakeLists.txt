cmake_minimum_required(VERSION 3.20)
project(autorotation_optimizer LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(NLopt REQUIRED)

add_library(autorotation_core
    src/aero_client.cpp
    src/rotor_model.cpp
    src/optimizer.cpp
    src/result_io.cpp
)

target_include_directories(autorotation_core PUBLIC include)
target_link_libraries(autorotation_core PUBLIC NLopt::nlopt)
target_compile_options(autorotation_core PRIVATE -Wall -Wextra -Wpedantic)

add_executable(autorotation_opt src/main.cpp)
target_link_libraries(autorotation_opt PRIVATE autorotation_core)
target_compile_options(autorotation_opt PRIVATE -Wall -Wextra -Wpedantic)

include(CTest)
if(BUILD_TESTING)
    add_executable(autorotation_core_tests tests/core_tests.cpp)
    target_link_libraries(autorotation_core_tests PRIVATE autorotation_core)
    target_compile_definitions(autorotation_core_tests PRIVATE
        AUTOROTATION_SOURCE_DIR="${CMAKE_SOURCE_DIR}/..")
    target_compile_options(autorotation_core_tests PRIVATE -Wall -Wextra -Wpedantic)
    add_test(NAME autorotation_core_tests COMMAND autorotation_core_tests)
endif()
