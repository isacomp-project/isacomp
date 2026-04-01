cmake_minimum_required(VERSION 3.9.6)

project(ila_examples)

# C++17 required
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find ILAng package
find_package(ilang REQUIRED)

# Export to JSON example
add_executable(export_to_json export_to_json.cc)
target_link_libraries(export_to_json PRIVATE ilang::ilang)

# If you have a specific ILA model from IMDb, you can add it here
# For example, to export the AES model:
# add_executable(export_aes export_aes_to_json.cc)
# target_link_libraries(export_aes PRIVATE ilang::ilang)
# target_include_directories(export_aes PRIVATE ../IMDb/IMDb_Accls/ILA_AES/include)
