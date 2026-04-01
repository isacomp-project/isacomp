/* Simple ADD instruction for testing */

val add_test : (bits(32), bits(32)) -> bits(32)

function add_test(rs1_val, rs2_val) = {
  let result = rs1_val + rs2_val;
  result
}
