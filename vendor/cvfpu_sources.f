// CVFPU source file list for isacomp
// Include this file with your simulator/synthesis tool
// Usage: vlog -f cvfpu_sources.f

// Common cells (dependencies)
+incdir+common_cells/include
common_cells/src/cf_math_pkg.sv
common_cells/src/lzc.sv
common_cells/src/rr_arb_tree.sv

// FPU div/sqrt MVP (PULP)
+incdir+fpu_div_sqrt_mvp/hdl
fpu_div_sqrt_mvp/hdl/defs_div_sqrt_mvp.sv
fpu_div_sqrt_mvp/hdl/preprocess_mvp.sv
fpu_div_sqrt_mvp/hdl/nrbd_nrsc_mvp.sv
fpu_div_sqrt_mvp/hdl/control_mvp.sv
fpu_div_sqrt_mvp/hdl/iteration_div_sqrt_mvp.sv
fpu_div_sqrt_mvp/hdl/norm_div_sqrt_mvp.sv
fpu_div_sqrt_mvp/hdl/div_sqrt_top_mvp.sv
fpu_div_sqrt_mvp/hdl/div_sqrt_mvp_wrapper.sv

// CVFPU core
+incdir+cvfpu/src
cvfpu/src/fpnew_pkg.sv
cvfpu/src/fpnew_classifier.sv
cvfpu/src/fpnew_rounding.sv
cvfpu/src/fpnew_fma.sv
cvfpu/src/fpnew_fma_multi.sv
cvfpu/src/fpnew_cast_multi.sv
cvfpu/src/fpnew_noncomp.sv
cvfpu/src/fpnew_divsqrt_multi.sv
cvfpu/src/fpnew_opgroup_fmt_slice.sv
cvfpu/src/fpnew_opgroup_multifmt_slice.sv
cvfpu/src/fpnew_opgroup_block.sv
cvfpu/src/fpnew_top.sv

// T-Head E906 div/sqrt (TH32 option)
cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/clk/rtl/gated_clk_cell.v
cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_ctrl.v
cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_ff1.v
cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_pack_single.v
cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_prepare.v
cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_round_single.v
cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_special.v
cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_srt_single.v
cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fdsu/rtl/pa_fdsu_top.v
cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fpu/rtl/pa_fpu_dp.v
cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fpu/rtl/pa_fpu_frbus.v
cvfpu/vendor/opene906/E906_RTL_FACTORY/gen_rtl/fpu/rtl/pa_fpu_src_type.v

// isacomp CVFPU wrapper
cvfpu_wrapper.sv
