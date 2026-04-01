//! PyO3 Python bindings for isacomp-core.
//!
//! Exposes the core ISA compilation infrastructure to Python as the
//! `isacomp_core` module.

use std::collections::HashMap;

use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use serde_json::{json, Value};

use crate::branch_prediction;
use crate::branch_target_buffer;
use crate::cache_optimization;
use crate::graph_merger::ResourceGraphMerger;
use crate::hazard_resolution::{HazardAnalyzer, HazardResolver};
use crate::isa_parser::ISAParser;
use crate::memory_access_transform::{MemoryAccessTransform, MemoryAccessTransformSpec};
use crate::memory_externalization::{self, MemoryExternalizationSpec};
use crate::multi_cycle_ops;
use crate::pipeline_config;
use crate::pipelining_optimization::PipelineTransform;
use crate::register_renaming;
use crate::resource_graph::{self, ResourceGraph};
use crate::return_address_stack;
use crate::verilog_generator;

// ===========================================================================
// PyNode — read-only view of a Node
// ===========================================================================

/// A node in the resource graph.
#[pyclass(name = "Node")]
#[derive(Clone)]
pub struct PyNode {
    inner: resource_graph::Node,
}

#[pymethods]
impl PyNode {
    /// Create a new Node with id, optional data dict, and optional uarch_time.
    #[new]
    #[pyo3(signature = (node_id, data=None, uarch_time=None))]
    fn new(node_id: &str, data: Option<PyObject>, uarch_time: Option<i64>) -> PyResult<Self> {
        let mut node_data: HashMap<String, Value> = HashMap::new();
        if let Some(d) = data {
            Python::with_gil(|py| -> PyResult<()> {
                let dict = d.downcast_bound::<pyo3::types::PyDict>(py)
                    .map_err(|_| PyValueError::new_err("data must be a dict"))?;
                for (k, v) in dict.iter() {
                    let key: String = k.extract()?;
                    let val = py_to_json_value(v.as_unbound().clone_ref(py), py)?;
                    node_data.insert(key, val);
                }
                Ok(())
            })?;
        }
        let data_opt = if node_data.is_empty() { None } else { Some(node_data) };
        let ut = uarch_time.unwrap_or(0);
        let node = resource_graph::Node::new(
            Some(node_id.into()), data_opt,
            false, false, None, false, None, None, false, false,
            ut, false, true, None, None,
        );
        Ok(PyNode { inner: node })
    }

    #[getter]
    fn id(&self) -> &str {
        &self.inner.id
    }

    #[getter]
    fn data(&self) -> PyResult<PyObject> {
        Python::with_gil(|py| json_value_to_py(py, &Value::Object(
            self.inner.data.iter().map(|(k, v)| (k.clone(), v.clone())).collect()
        )))
    }

    #[getter]
    fn is_arch_state(&self) -> bool {
        self.inner.is_arch_state
    }

    #[getter]
    fn is_shared(&self) -> bool {
        self.inner.is_shared
    }

    #[getter]
    fn is_uarch_state(&self) -> bool {
        self.inner.is_uarch_state
    }

    #[getter]
    fn used_as_index(&self) -> bool {
        self.inner.used_as_index
    }

    #[getter]
    fn latency(&self) -> i64 {
        self.inner.latency
    }

    #[getter]
    fn variable_latency(&self) -> bool {
        self.inner.variable_latency
    }

    #[getter]
    fn incoming_edges(&self) -> Vec<String> {
        self.inner.incoming_edges.iter().cloned().collect()
    }

    #[getter]
    fn outgoing_edges(&self) -> Vec<String> {
        self.inner.outgoing_edges.iter().cloned().collect()
    }

    fn __repr__(&self) -> String {
        format!("{}", self.inner)
    }
}

// ===========================================================================
// PyEdge — read-only view of an Edge
// ===========================================================================

/// Lightweight wrapper returned by Edge.source / Edge.target so that
/// `edge.source.id` works the same as the Python Node-based API.
#[pyclass(name = "EdgeEndpoint")]
#[derive(Clone)]
pub struct PyEdgeEndpoint {
    /// The node ID string.
    node_id: String,
}

#[pymethods]
impl PyEdgeEndpoint {
    #[getter]
    fn id(&self) -> &str {
        &self.node_id
    }

    fn __repr__(&self) -> String {
        self.node_id.clone()
    }

    fn __str__(&self) -> String {
        self.node_id.clone()
    }

    fn __eq__(&self, other: &str) -> bool {
        self.node_id == other
    }

    fn __hash__(&self) -> u64 {
        use std::hash::{Hash, Hasher};
        let mut h = std::collections::hash_map::DefaultHasher::new();
        self.node_id.hash(&mut h);
        h.finish()
    }

    /// String-like methods so `edge.source.endswith(...)` etc. work.
    fn endswith(&self, suffix: &str) -> bool {
        self.node_id.ends_with(suffix)
    }

    fn startswith(&self, prefix: &str) -> bool {
        self.node_id.starts_with(prefix)
    }

    fn __contains__(&self, substr: &str) -> bool {
        self.node_id.contains(substr)
    }
}

/// An edge in the resource graph.
#[pyclass(name = "Edge")]
#[derive(Clone)]
pub struct PyEdge {
    inner: resource_graph::Edge,
}

#[pymethods]
impl PyEdge {
    /// Create a new Edge from source to target with optional data dict.
    #[new]
    #[pyo3(signature = (source, target, data=None))]
    fn new(source: PyObject, target: PyObject, data: Option<PyObject>) -> PyResult<Self> {
        // Accept either Node objects or strings for source/target
        let src_id: String = Python::with_gil(|py| {
            if let Ok(node) = source.extract::<PyRef<PyNode>>(py) {
                Ok(node.inner.id.clone())
            } else if let Ok(ep) = source.extract::<PyRef<PyEdgeEndpoint>>(py) {
                Ok(ep.node_id.clone())
            } else {
                source.extract::<String>(py)
            }
        })?;
        let tgt_id: String = Python::with_gil(|py| {
            if let Ok(node) = target.extract::<PyRef<PyNode>>(py) {
                Ok(node.inner.id.clone())
            } else if let Ok(ep) = target.extract::<PyRef<PyEdgeEndpoint>>(py) {
                Ok(ep.node_id.clone())
            } else {
                target.extract::<String>(py)
            }
        })?;
        let edge_data = if let Some(d) = data {
            let mut map: HashMap<String, Value> = HashMap::new();
            Python::with_gil(|py| -> PyResult<()> {
                let dict = d.downcast_bound::<pyo3::types::PyDict>(py)
                    .map_err(|_| PyValueError::new_err("data must be a dict"))?;
                for (k, v) in dict.iter() {
                    let key: String = k.extract()?;
                    let val = py_to_json_value(v.as_unbound().clone_ref(py), py)?;
                    map.insert(key, val);
                }
                Ok(())
            })?;
            Some(map)
        } else {
            None
        };
        let edge = resource_graph::Edge::new(src_id, tgt_id, None, edge_data);
        Ok(PyEdge { inner: edge })
    }

    #[getter]
    fn id(&self) -> &str {
        &self.inner.id
    }

    #[getter]
    fn source(&self) -> PyEdgeEndpoint {
        PyEdgeEndpoint { node_id: self.inner.source.clone() }
    }

    #[getter]
    fn target(&self) -> PyEdgeEndpoint {
        PyEdgeEndpoint { node_id: self.inner.target.clone() }
    }

    #[getter]
    fn data(&self) -> PyResult<PyObject> {
        Python::with_gil(|py| json_value_to_py(py, &Value::Object(
            self.inner.data.iter().map(|(k, v)| (k.clone(), v.clone())).collect()
        )))
    }

    fn __repr__(&self) -> String {
        format!("{}", self.inner)
    }
}

// ===========================================================================
// PyResourceGraph
// ===========================================================================

/// A resource graph containing nodes and edges representing an ISA or merged
/// instruction set.
#[pyclass(name = "ResourceGraph")]
#[derive(Clone)]
pub struct PyResourceGraph {
    pub(crate) inner: ResourceGraph,
}

#[pymethods]
impl PyResourceGraph {
    #[new]
    fn new() -> Self {
        PyResourceGraph {
            inner: ResourceGraph::new(),
        }
    }

    /// Return a dict of {node_id: Node}.
    #[getter]
    fn nodes(&self) -> HashMap<String, PyNode> {
        self.inner
            .nodes
            .iter()
            .map(|(k, v)| (k.clone(), PyNode { inner: v.clone() }))
            .collect()
    }

    /// Return a dict of {edge_id: Edge}.
    #[getter]
    fn edges(&self) -> HashMap<String, PyEdge> {
        self.inner
            .edges
            .iter()
            .map(|(k, v)| (k.clone(), PyEdge { inner: v.clone() }))
            .collect()
    }

    /// Number of nodes.
    fn node_count(&self) -> usize {
        self.inner.nodes.len()
    }

    /// Number of edges.
    fn edge_count(&self) -> usize {
        self.inner.edges.len()
    }

    /// Serialize the graph to a JSON string.
    fn to_json(&self) -> PyResult<String> {
        let val = self.inner.to_json();
        serde_json::to_string_pretty(&val)
            .map_err(|e| PyValueError::new_err(format!("JSON serialization error: {e}")))
    }

    /// Deserialize a graph from a JSON string.
    #[staticmethod]
    fn from_json(json_str: &str) -> PyResult<Self> {
        let val: Value = serde_json::from_str(json_str)
            .map_err(|e| PyValueError::new_err(format!("JSON parse error: {e}")))?;
        let graph = ResourceGraph::from_json(&val)
            .map_err(|e| PyValueError::new_err(e))?;
        Ok(PyResourceGraph { inner: graph })
    }

    fn __repr__(&self) -> String {
        format!(
            "ResourceGraph(nodes={}, edges={})",
            self.inner.nodes.len(),
            self.inner.edges.len()
        )
    }

    fn __len__(&self) -> usize {
        self.inner.nodes.len()
    }

    /// Check if a node exists in the graph.
    fn has_node(&self, node_id: &str) -> bool {
        self.inner.nodes.contains_key(node_id)
    }

    /// Find all edges from a source node. Returns list of (edge_id, target_id).
    fn find_edges_from(&self, src_id: &str) -> Vec<(String, String)> {
        if let Some(node) = self.inner.nodes.get(src_id) {
            node.outgoing_edges.iter().filter_map(|eid| {
                self.inner.edges.get(eid).map(|e| (eid.clone(), e.target.clone()))
            }).collect()
        } else {
            Vec::new()
        }
    }

    /// Find all edges to a target node. Returns list of (edge_id, source_id).
    fn find_edges_to(&self, tgt_id: &str) -> Vec<(String, String)> {
        if let Some(node) = self.inner.nodes.get(tgt_id) {
            node.incoming_edges.iter().filter_map(|eid| {
                self.inner.edges.get(eid).map(|e| (eid.clone(), e.source.clone()))
            }).collect()
        } else {
            Vec::new()
        }
    }

    /// Find the edge ID from src to tgt, or None.
    fn find_edge(&self, src_id: &str, tgt_id: &str) -> Option<String> {
        if let Some(node) = self.inner.nodes.get(src_id) {
            for eid in &node.outgoing_edges {
                if let Some(e) = self.inner.edges.get(eid) {
                    if e.target == tgt_id {
                        return Some(eid.clone());
                    }
                }
            }
        }
        None
    }

    /// Find edges from src to any target ending with suffix.
    /// Returns list of (edge_id, target_id).
    fn find_edges_to_suffix(&self, src_id: &str, suffix: &str) -> Vec<(String, String)> {
        if let Some(node) = self.inner.nodes.get(src_id) {
            let suffixed = format!("_{}", suffix);
            node.outgoing_edges.iter().filter_map(|eid| {
                self.inner.edges.get(eid).and_then(|e| {
                    if e.target == suffix || e.target.ends_with(&suffixed) {
                        Some((eid.clone(), e.target.clone()))
                    } else {
                        None
                    }
                })
            }).collect()
        } else {
            Vec::new()
        }
    }

    /// Find edges from any source ending with suffix to tgt.
    /// Returns list of (edge_id, source_id).
    fn find_edges_from_suffix(&self, suffix: &str, tgt_id: &str) -> Vec<(String, String)> {
        if let Some(node) = self.inner.nodes.get(tgt_id) {
            let suffixed = format!("_{}", suffix);
            node.incoming_edges.iter().filter_map(|eid| {
                self.inner.edges.get(eid).and_then(|e| {
                    if e.source == suffix || e.source.ends_with(&suffixed) {
                        Some((eid.clone(), e.source.clone()))
                    } else {
                        None
                    }
                })
            }).collect()
        } else {
            Vec::new()
        }
    }

    /// Add a comparator node (e.g. a == b).
    fn add_comparator_node(&mut self, node_id: &str, left_id: &str, right_id: &str, op: &str) {
        use crate::resource_graph::{Node, Edge};
        let mut data: HashMap<String, Value> = HashMap::new();
        data.insert("type".into(), json!("operation"));
        data.insert("operator".into(), json!(op));
        data.insert("name".into(), json!(node_id));
        data.insert("bit_width".into(), json!(1));
        let node = Node::new(Some(node_id.into()), Some(data), false, false, None, false, None, None, false, false, 0, false, true, None, None);
        self.inner.add_node(node);

        let mut e1d: HashMap<String, Value> = HashMap::new();
        e1d.insert("type".into(), json!("left_operand"));
        e1d.insert("position".into(), json!("left"));
        let e1 = Edge::new(left_id.into(), node_id.into(), None, Some(e1d));
        self.inner.add_edge(e1);

        let mut e2d: HashMap<String, Value> = HashMap::new();
        e2d.insert("type".into(), json!("right_operand"));
        e2d.insert("position".into(), json!("right"));
        let e2 = Edge::new(right_id.into(), node_id.into(), None, Some(e2d));
        self.inner.add_edge(e2);
    }

    /// Add an AND node combining two signals.
    fn add_and_node(&mut self, node_id: &str, left_id: &str, right_id: &str) {
        use crate::resource_graph::{Node, Edge};
        let mut data: HashMap<String, Value> = HashMap::new();
        data.insert("type".into(), json!("operation"));
        data.insert("operator".into(), json!("&&"));
        data.insert("name".into(), json!(node_id));
        data.insert("bit_width".into(), json!(1));
        let node = Node::new(Some(node_id.into()), Some(data), false, false, None, false, None, None, false, false, 0, false, true, None, None);
        self.inner.add_node(node);

        let mut e1d: HashMap<String, Value> = HashMap::new();
        e1d.insert("type".into(), json!("left_operand"));
        e1d.insert("position".into(), json!("left"));
        let e1 = Edge::new(left_id.into(), node_id.into(), None, Some(e1d));
        self.inner.add_edge(e1);

        let mut e2d: HashMap<String, Value> = HashMap::new();
        e2d.insert("type".into(), json!("right_operand"));
        e2d.insert("position".into(), json!("right"));
        let e2 = Edge::new(right_id.into(), node_id.into(), None, Some(e2d));
        self.inner.add_edge(e2);
    }

    /// Add a node to the graph (accepts PyNode).
    fn add_node(&mut self, node: &PyNode) {
        self.inner.add_node(node.inner.clone());
    }

    /// Add an edge to the graph (accepts PyEdge).
    fn add_edge(&mut self, edge: &PyEdge) {
        self.inner.add_edge(edge.inner.clone());
    }

    /// Add a stall_condition edge from a signal to a stall controller.
    fn add_stall_condition_edge(&mut self, source_id: &str, target_id: &str) {
        use crate::resource_graph::Edge;
        let mut edge_data: HashMap<String, Value> = HashMap::new();
        edge_data.insert("type".into(), json!("stall_condition"));
        edge_data.insert("pipeline_component".into(), json!(true));
        let edge = Edge::new(source_id.into(), target_id.into(), None, Some(edge_data));
        self.inner.add_edge(edge);
    }

    /// Save graph to a JSON file.
    fn save_to_file(&self, filename: &str) -> PyResult<()> {
        self.inner.save_to_file(filename)
            .map_err(|e| PyValueError::new_err(format!("Failed to save graph: {e}")))
    }

    /// Infer uarch_time on graph nodes (matches Python ResourceGraph.infer_uarch_time).
    #[pyo3(signature = (force_reinfer=false))]
    fn infer_uarch_time(&mut self, force_reinfer: bool) {
        self.inner.infer_uarch_time(force_reinfer);
    }

    /// Infer pipe_time on graph nodes (matches Python ResourceGraph.infer_pipe_time).
    #[pyo3(signature = (force_reinfer=false))]
    fn infer_pipe_time(&mut self, force_reinfer: bool) {
        self.inner.infer_pipe_time(force_reinfer);
    }
}

// ===========================================================================
// PyISAParser
// ===========================================================================

/// ISA specification parser.
#[pyclass(name = "ISAParser")]
pub struct PyISAParser {
    inner: ISAParser,
}

#[pymethods]
impl PyISAParser {
    #[new]
    fn new() -> Self {
        PyISAParser {
            inner: ISAParser::new(),
        }
    }

    /// Parse an ISA file and return a ResourceGraph.
    fn parse_file(&mut self, file_path: &str) -> PyResult<PyResourceGraph> {
        let graph = self
            .inner
            .parse_file(file_path, None)
            .map_err(|e| PyValueError::new_err(e))?;
        Ok(PyResourceGraph { inner: graph })
    }
}

// ===========================================================================
// merge_instructions — top-level convenience function
// ===========================================================================

/// Parse and merge multiple ISA instruction files into a single ResourceGraph.
///
/// Args:
///     instruction_files: dict mapping instruction names to ISA file paths
///     pc_name: name of the program counter register (default "pc")
///     defines: optional dict of preprocessor defines
///
/// Returns:
///     A merged ResourceGraph
#[pyfunction]
#[pyo3(signature = (instruction_files, pc_name = "pc", defines = None))]
fn merge_instructions(
    instruction_files: HashMap<String, String>,
    pc_name: &str,
    defines: Option<HashMap<String, String>>,
) -> PyResult<PyResourceGraph> {
    let mut merger = ResourceGraphMerger::new(defines);

    for (instr_name, isa_file) in &instruction_files {
        merger
            .add_instruction(instr_name, isa_file)
            .map_err(|e| PyValueError::new_err(format!("Failed to add instruction '{instr_name}': {e}")))?;
    }

    let merged = merger
        .merge_graphs(Some(pc_name))
        .map_err(|e| PyValueError::new_err(format!("Merge failed: {e}")))?;

    Ok(PyResourceGraph { inner: merged })
}

// ===========================================================================
// VerilogGenerator
// ===========================================================================

/// Verilog RTL generator.
#[pyclass(name = "VerilogGenerator")]
pub struct PyVerilogGenerator {
    graph: PyResourceGraph,
    module_name: String,
}

#[pymethods]
impl PyVerilogGenerator {
    #[new]
    fn new(graph: PyResourceGraph, module_name: &str) -> Self {
        PyVerilogGenerator {
            graph,
            module_name: module_name.to_string(),
        }
    }

    /// Generate Verilog code from the resource graph.
    fn generate(&self) -> String {
        verilog_generator::generate_verilog(&self.graph.inner, &self.module_name)
    }
}

// ===========================================================================
// MemoryAccessTransform
// ===========================================================================

/// Memory access transformation spec.
#[pyclass(name = "MemoryAccessTransformSpec")]
#[derive(Clone)]
pub struct PyMemoryAccessTransformSpec {
    inner: MemoryAccessTransformSpec,
}

#[pymethods]
impl PyMemoryAccessTransformSpec {
    #[new]
    #[pyo3(signature = (memory, strategy, current_width, target_width, direction))]
    fn new(
        memory: &str,
        strategy: &str,
        current_width: i64,
        target_width: i64,
        direction: &str,
    ) -> PyResult<Self> {
        let spec = MemoryAccessTransformSpec::new(memory, strategy, current_width, target_width, direction)
            .map_err(|e| PyValueError::new_err(e))?;
        Ok(PyMemoryAccessTransformSpec { inner: spec })
    }
}

/// Memory access transform — modifies a graph in-place.
#[pyclass(name = "MemoryAccessTransform")]
pub struct PyMemoryAccessTransform {
    graph: PyResourceGraph,
}

#[pymethods]
impl PyMemoryAccessTransform {
    #[new]
    fn new(graph: PyResourceGraph) -> Self {
        PyMemoryAccessTransform { graph }
    }

    /// Apply a transformation to the graph. Returns a dict with result info.
    #[pyo3(signature = (spec, dry_run=false))]
    fn apply_transformation(&mut self, spec: &PyMemoryAccessTransformSpec, dry_run: bool) -> PyResult<PyObject> {
        let mut transform = MemoryAccessTransform::new(&mut self.graph.inner);
        let result = transform.apply_transformation(&spec.inner, dry_run);
        Python::with_gil(|py| {
            let dict = pyo3::types::PyDict::new_bound(py);
            dict.set_item("transformed", result.transformed)?;
            dict.set_item("reason", &result.reason)?;
            dict.set_item("nodes_added", &result.nodes_added)?;
            dict.set_item("nodes_removed", &result.nodes_removed)?;
            dict.set_item("nodes_updated", &result.nodes_updated)?;
            Ok(dict.into_any().unbind())
        })
    }

    /// Enable write-to-read forwarding on a memory (e.g., register file).
    ///
    /// When enabled, the Verilog generator emits a transparent forwarding mux
    /// and the hazard resolver skips stalls for canonical read/write pairs.
    fn enable_write_read_forwarding(&mut self, memory_name: &str) -> PyResult<PyObject> {
        let success = {
            let mut transform = MemoryAccessTransform::new(&mut self.graph.inner);
            transform.enable_write_read_forwarding(memory_name)
        };
        Python::with_gil(|py| {
            let dict = pyo3::types::PyDict::new_bound(py);
            dict.set_item("enabled", success)?;
            dict.set_item("memory", memory_name)?;
            dict.set_item("property", "write_read_fwd")?;
            Ok(dict.into_any().unbind())
        })
    }

    /// Get the transformed graph back.
    fn get_graph(&self) -> PyResourceGraph {
        self.graph.clone()
    }
}

// ===========================================================================
// MemoryExternalization
// ===========================================================================

/// Apply memory externalization to a resource graph.
#[pyfunction]
#[pyo3(signature = (graph, memory_name, create_read_port=true, create_write_port=true, variable_latency=false))]
fn apply_memory_externalization(
    graph: &mut PyResourceGraph,
    memory_name: &str,
    create_read_port: bool,
    create_write_port: bool,
    variable_latency: bool,
) -> PyResult<bool> {
    let mut spec = MemoryExternalizationSpec::new(memory_name);
    spec.create_read_port = create_read_port;
    spec.create_write_port = create_write_port;
    spec.variable_latency = variable_latency;
    Ok(memory_externalization::apply_memory_externalization(&mut graph.inner, &spec))
}

// ===========================================================================
// PipelineConfig
// ===========================================================================

/// A pipeline cut (boundary between stages), matching Python's PipelineCut dataclass.
#[pyclass(name = "PipelineCut")]
#[derive(Clone)]
pub struct PyPipelineCut {
    #[pyo3(get)]
    name: String,
    #[pyo3(get)]
    description: String,
    #[pyo3(get)]
    stage_index: usize,
}

#[pymethods]
impl PyPipelineCut {
    fn __repr__(&self) -> String {
        format!("Cut -> {} (stage {})", self.name, self.stage_index)
    }
}

/// Pipeline configuration.
#[pyclass(name = "PipelineConfig")]
#[derive(Clone)]
pub struct PyPipelineConfig {
    pub(crate) inner: pipeline_config::PipelineConfig,
}

#[pymethods]
impl PyPipelineConfig {
    #[getter]
    fn num_stages(&self) -> usize {
        self.inner.num_stages
    }

    #[getter]
    fn stage_names(&self) -> Vec<String> {
        self.inner.stage_names.clone()
    }

    #[getter]
    fn register_read_stage(&self) -> &str {
        &self.inner.register_read_stage
    }

    #[getter]
    fn register_write_stage(&self) -> &str {
        &self.inner.register_write_stage
    }

    #[getter]
    fn memory_stage(&self) -> &str {
        &self.inner.memory_stage
    }

    #[getter]
    fn branch_resolution_stage(&self) -> &str {
        &self.inner.branch_resolution_stage
    }

    #[getter]
    fn prefix(&self) -> &str {
        &self.inner.prefix
    }

    /// Get cuts as list of PipelineCut objects (matches Python dataclass API).
    #[getter]
    fn cuts(&self) -> Vec<PyPipelineCut> {
        self.inner.cuts.iter().map(|c| PyPipelineCut {
            name: c.name.clone(),
            description: c.description.clone(),
            stage_index: c.stage_index,
        }).collect()
    }

    fn __repr__(&self) -> String {
        format!("PipelineConfig(stages={}, names={:?})", self.inner.num_stages, self.inner.stage_names)
    }
}

/// Get pipeline configuration for given number of stages.
#[pyfunction]
fn get_pipeline_config(num_stages: usize) -> PyResult<PyPipelineConfig> {
    pipeline_config::get_pipeline_config(num_stages)
        .map(|c| PyPipelineConfig { inner: c })
        .map_err(|e| PyValueError::new_err(e))
}

// ===========================================================================
// PipelineTransform (class-based API matching Python)
// ===========================================================================

/// Pipeline transformation engine.
///
/// Matches the Python PipelineTransform API:
///   transform = PipelineTransform(graph)
///   transform.set_stage_order(stage_order, stage_indices)
///   success = transform.add_multiple_pipeline_stages(cut_specs)
///   summary = transform.get_pipeline_summary()
#[pyclass(name = "PipelineTransform")]
pub struct PyPipelineTransform {
    graph: PyResourceGraph,
    stage_order: Option<Vec<String>>,
    stage_indices: Option<HashMap<String, i64>>,
}

#[pymethods]
impl PyPipelineTransform {
    #[new]
    fn new(graph: PyResourceGraph) -> Self {
        PyPipelineTransform {
            graph,
            stage_order: None,
            stage_indices: None,
        }
    }

    /// Set explicit stage order for pipeline transforms.
    fn set_stage_order(&mut self, stage_order: Vec<String>, stage_indices: HashMap<String, usize>) {
        let indices_i64: HashMap<String, i64> = stage_indices.into_iter()
            .map(|(k, v)| (k, v as i64))
            .collect();
        self.stage_order = Some(stage_order);
        self.stage_indices = Some(indices_i64);
    }

    /// Add multiple pipeline stages.
    ///
    /// cut_specs: list of dicts with 'edges', 'after_stage', 'stage_index'
    fn add_multiple_pipeline_stages(&mut self, cut_specs: Vec<HashMap<String, PyObject>>) -> PyResult<bool> {
        let mut transform = PipelineTransform::new(&mut self.graph.inner);

        if let Some(ref order) = self.stage_order {
            transform.set_stage_order(order.clone(), self.stage_indices.clone());
        }

        let mut rust_cuts: Vec<crate::pipelining_optimization::CutSpec> = Vec::new();
        Python::with_gil(|py| -> PyResult<()> {
            for spec_dict in &cut_specs {
                let edges_obj = spec_dict.get("edges")
                    .ok_or_else(|| PyValueError::new_err("Cut spec missing 'edges'"))?;
                let edges: Vec<String> = edges_obj.extract(py)?;

                let stage_name_obj = spec_dict.get("after_stage")
                    .ok_or_else(|| PyValueError::new_err("Cut spec missing 'after_stage'"))?;
                let stage_name: String = stage_name_obj.extract(py)?;

                let stage_index_obj = spec_dict.get("stage_index")
                    .ok_or_else(|| PyValueError::new_err("Cut spec missing 'stage_index'"))?;
                let stage_index: usize = stage_index_obj.extract(py)?;

                rust_cuts.push(crate::pipelining_optimization::CutSpec {
                    edges,
                    after_stage: stage_name,
                    stage_index: Some(stage_index as i64),
                });
            }
            Ok(())
        })?;

        let success = transform.add_multiple_pipeline_stages(&rust_cuts);

        if success {
            let summary = transform.get_pipeline_summary();
            log::info!("Pipeline transformation successful!");
            log::info!("  Total stages: {}", summary.total_stages);
            log::info!("  Max uarch_time: {}", summary.max_uarch_time);
        }

        Ok(success)
    }

    /// Get pipeline summary as dict.
    fn get_pipeline_summary(&self) -> PyResult<PyObject> {
        Python::with_gil(|py| {
            let dict = pyo3::types::PyDict::new_bound(py);

            let mut pipe_reg_count = 0;
            let mut stall_ctrl_count = 0;
            let mut valid_count = 0;
            let mut max_time: i64 = 0;

            for (_, node) in &self.graph.inner.nodes {
                let nt = node.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
                if nt == "pipeline_register" {
                    pipe_reg_count += 1;
                } else if nt == "pipeline_stall_controller" {
                    stall_ctrl_count += 1;
                }
                if node.id.contains("_valid_") && node.id.starts_with("PIPE_") {
                    valid_count += 1;
                }
                if let Some(pt) = node.pipe_time {
                    if pt > max_time { max_time = pt; }
                }
            }

            dict.set_item("pipeline_registers", pipe_reg_count)?;
            dict.set_item("stall_controllers", stall_ctrl_count)?;
            dict.set_item("validity_signals", valid_count)?;
            dict.set_item("max_pipe_time", max_time)?;
            dict.set_item("total_stages", max_time + 1)?;
            dict.set_item("max_uarch_time", self.graph.inner.get_max_uarch_time())?;

            Ok(dict.into_any().unbind())
        })
    }

    /// Get the transformed graph.
    fn get_graph(&self) -> PyResourceGraph {
        self.graph.clone()
    }
}

/// Also keep the function-based API for convenience.
#[pyfunction]
#[pyo3(signature = (graph, cut_specs, stage_order=None, stage_indices=None))]
fn apply_pipeline_transforms(
    graph: &mut PyResourceGraph,
    cut_specs: Vec<HashMap<String, PyObject>>,
    stage_order: Option<Vec<String>>,
    stage_indices: Option<HashMap<String, usize>>,
) -> PyResult<bool> {
    let mut transform = PipelineTransform::new(&mut graph.inner);

    if let Some(order) = stage_order {
        let indices_i64: Option<HashMap<String, i64>> = stage_indices.map(|m| {
            m.into_iter().map(|(k, v)| (k, v as i64)).collect()
        });
        transform.set_stage_order(order, indices_i64);
    }

    let mut rust_cuts: Vec<crate::pipelining_optimization::CutSpec> = Vec::new();
    Python::with_gil(|py| -> PyResult<()> {
        for spec_dict in &cut_specs {
            let edges_obj = spec_dict.get("edges")
                .ok_or_else(|| PyValueError::new_err("Cut spec missing 'edges'"))?;
            let edges: Vec<String> = edges_obj.extract(py)?;

            let stage_name_obj = spec_dict.get("after_stage")
                .ok_or_else(|| PyValueError::new_err("Cut spec missing 'after_stage'"))?;
            let stage_name: String = stage_name_obj.extract(py)?;

            let stage_index_obj = spec_dict.get("stage_index")
                .ok_or_else(|| PyValueError::new_err("Cut spec missing 'stage_index'"))?;
            let stage_index: usize = stage_index_obj.extract(py)?;

            rust_cuts.push(crate::pipelining_optimization::CutSpec {
                edges,
                after_stage: stage_name,
                stage_index: Some(stage_index as i64),
            });
        }
        Ok(())
    })?;

    Ok(transform.add_multiple_pipeline_stages(&rust_cuts))
}

/// Get a pipeline summary from a graph.
#[pyfunction]
fn get_pipeline_summary(graph: &PyResourceGraph) -> PyResult<PyObject> {
    Python::with_gil(|py| {
        let dict = pyo3::types::PyDict::new_bound(py);

        let mut pipe_reg_count = 0;
        let mut stall_ctrl_count = 0;
        let mut valid_count = 0;
        let mut max_time: i64 = 0;

        for (_, node) in &graph.inner.nodes {
            let nt = node.data.get("type").and_then(|v| v.as_str()).unwrap_or("");
            if nt == "pipeline_register" {
                pipe_reg_count += 1;
            } else if nt == "pipeline_stall_controller" {
                stall_ctrl_count += 1;
            }
            if node.id.contains("_valid_") && node.id.starts_with("PIPE_") {
                valid_count += 1;
            }
            if let Some(pt) = node.pipe_time {
                if pt > max_time { max_time = pt; }
            }
        }

        dict.set_item("pipeline_registers", pipe_reg_count)?;
        dict.set_item("stall_controllers", stall_ctrl_count)?;
        dict.set_item("validity_signals", valid_count)?;
        dict.set_item("max_pipe_time", max_time)?;
        dict.set_item("total_stages", max_time + 1)?;
        dict.set_item("max_uarch_time", graph.inner.get_max_uarch_time())?;

        Ok(dict.into_any().unbind())
    })
}

// ===========================================================================
// HazardResolution (class-based API matching Python)
// ===========================================================================

/// Hazard resolution strategy enum.
#[pyclass(name = "HazardResolutionStrategy")]
#[derive(Clone)]
pub struct PyHazardResolutionStrategy;

#[pymethods]
impl PyHazardResolutionStrategy {
    #[classattr]
    const STALL: &'static str = "stall";

    #[classattr]
    const BYPASS: &'static str = "bypass";
}

/// Hazard analyzer — detects pipeline hazards.
///
/// Matches Python API:
///   analyzer = HazardAnalyzer(graph, pc_name='pc')
///   analyzer.identify_pipeline_stages()
///   hazards = analyzer.analyze_hazards()
#[pyclass(name = "HazardAnalyzer")]
pub struct PyHazardAnalyzer {
    graph: PyResourceGraph,
    pc_name: String,
    hazards: Vec<crate::hazard_resolution::DetectedHazard>,
}

#[pymethods]
impl PyHazardAnalyzer {
    #[new]
    #[pyo3(signature = (graph, pc_name="pc"))]
    fn new(graph: PyResourceGraph, pc_name: &str) -> Self {
        PyHazardAnalyzer {
            graph,
            pc_name: pc_name.to_string(),
            hazards: Vec::new(),
        }
    }

    fn identify_pipeline_stages(&self) -> PyResult<PyObject> {
        let mut analyzer = HazardAnalyzer::new(&self.graph.inner, &self.pc_name);
        let stages = analyzer.identify_pipeline_stages();
        Python::with_gil(|py| {
            let list = pyo3::types::PyList::empty_bound(py);
            for s in stages {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("stage_index", s.stage_index)?;
                dict.set_item("stage_name", &s.stage_name)?;
                dict.set_item("pipeline_register_id", &s.pipeline_register_id)?;
                list.append(dict)?;
            }
            Ok(list.into_any().unbind())
        })
    }

    fn analyze_hazards(&mut self) -> PyResult<PyObject> {
        let mut analyzer = HazardAnalyzer::new(&self.graph.inner, &self.pc_name);
        analyzer.identify_pipeline_stages();
        let hazards = analyzer.analyze_hazards();
        self.hazards = hazards.to_vec();

        Python::with_gil(|py| {
            let list = pyo3::types::PyList::empty_bound(py);
            for h in &self.hazards {
                let dict = pyo3::types::PyDict::new_bound(py);
                dict.set_item("hazard_type", &h.hazard_type)?;
                dict.set_item("resource", &h.resource)?;
                dict.set_item("write_stage", h.write_stage)?;
                dict.set_item("write_stage_name", &h.write_stage_name)?;
                dict.set_item("write_access_node_id", &h.write_access_node_id)?;
                dict.set_item("write_index_node_id", &h.write_index_node_id)?;
                dict.set_item("write_index_name", &h.write_index_name)?;
                dict.set_item("read_stage", h.read_stage)?;
                dict.set_item("read_stage_name", &h.read_stage_name)?;
                dict.set_item("read_access_node_id", &h.read_access_node_id)?;
                dict.set_item("read_index_node_id", &h.read_index_node_id)?;
                dict.set_item("read_index_name", &h.read_index_name)?;
                dict.set_item("forwarding_distance", h.get_forwarding_distance())?;
                list.append(dict)?;
            }
            Ok(list.into_any().unbind())
        })
    }

    fn get_hazards(&self) -> Vec<PyObject> {
        Python::with_gil(|py| {
            self.hazards.iter().map(|h| {
                let dict = pyo3::types::PyDict::new_bound(py);
                let _ = dict.set_item("hazard_type", &h.hazard_type);
                let _ = dict.set_item("resource", &h.resource);
                let _ = dict.set_item("write_stage", h.write_stage);
                let _ = dict.set_item("read_stage", h.read_stage);
                dict.into_any().unbind()
            }).collect()
        })
    }
}

/// Hazard resolver — resolves detected hazards.
///
/// Matches Python API:
///   resolver = HazardResolver(graph, isa_states_to_gate=['pc_rd'], pipeline_config=config)
///   resolver.resolve_all_hazards(hazards)
///   resolver.add_control_hazard_handling(branch_conditions, jump_types, pc_mux_id)
///   resolver.gate_write_enables_with_validity()
#[pyclass(name = "HazardResolver")]
pub struct PyHazardResolver {
    graph: PyResourceGraph,
    isa_states_to_gate: Vec<String>,
    pipeline_config: Option<pipeline_config::PipelineConfig>,
}

#[pymethods]
impl PyHazardResolver {
    #[new]
    #[pyo3(signature = (graph, isa_states_to_gate=None, pipeline_config=None))]
    fn new(
        graph: PyResourceGraph,
        isa_states_to_gate: Option<Vec<String>>,
        pipeline_config: Option<PyPipelineConfig>,
    ) -> Self {
        PyHazardResolver {
            graph,
            isa_states_to_gate: isa_states_to_gate.unwrap_or_else(|| vec!["pc_rd".to_string()]),
            pipeline_config: pipeline_config.map(|c| c.inner),
        }
    }

    /// Resolve all detected hazards.
    #[pyo3(signature = (hazards=None, strategy="stall"))]
    fn resolve_all_hazards(&mut self, hazards: Option<PyObject>, strategy: &str) -> PyResult<bool> {
        // Re-analyze to get hazards in Rust types
        let mut detected = {
            let mut analyzer = HazardAnalyzer::new(&self.graph.inner, "pc");
            analyzer.identify_pipeline_stages();
            let h = analyzer.analyze_hazards();
            h.to_vec()
        };

        // Set resolution strategy on all hazards
        let resolution = match strategy {
            "bypass" => crate::hazard_resolution::HazardResolutionStrategy::Bypass,
            "none" => crate::hazard_resolution::HazardResolutionStrategy::None,
            _ => crate::hazard_resolution::HazardResolutionStrategy::Stall,
        };
        for h in &mut detected {
            h.resolution = resolution;
        }

        let mut resolver = HazardResolver::new(
            &mut self.graph.inner,
            self.isa_states_to_gate.clone(),
            self.pipeline_config.clone(),
        );

        Ok(resolver.resolve_all_hazards(&detected))
    }

    /// Add control hazard handling (branch flush).
    #[pyo3(signature = (branch_conditions=None, jump_types=None, pc_mux_id=None, resolution_stage=None, stage_order_override=None))]
    fn add_control_hazard_handling(
        &mut self,
        branch_conditions: Option<HashMap<String, String>>,
        jump_types: Option<Vec<String>>,
        pc_mux_id: Option<&str>,
        resolution_stage: Option<&str>,
        stage_order_override: Option<Vec<String>>,
    ) {
        let bc = branch_conditions.unwrap_or_default();
        let jt = jump_types.unwrap_or_default();

        let mut resolver = HazardResolver::new(
            &mut self.graph.inner,
            self.isa_states_to_gate.clone(),
            self.pipeline_config.clone(),
        );
        resolver.add_control_hazard_handling(&bc, &jt, pc_mux_id);
    }

    /// Gate write enables with validity signals.
    fn gate_write_enables_with_validity(&mut self) {
        let mut resolver = HazardResolver::new(
            &mut self.graph.inner,
            self.isa_states_to_gate.clone(),
            self.pipeline_config.clone(),
        );
        resolver.gate_write_enables_with_validity();
    }

    /// Get the modified graph.
    fn get_graph(&self) -> PyResourceGraph {
        self.graph.clone()
    }
}

/// Also keep the function-based API.
#[pyfunction]
#[pyo3(signature = (graph, pc_name="pc", strategy="stall", isa_states_to_gate=None, pipeline_config=None, branch_conditions=None, jump_types=None))]
fn apply_hazard_resolution(
    graph: &mut PyResourceGraph,
    pc_name: &str,
    strategy: &str,
    isa_states_to_gate: Option<Vec<String>>,
    pipeline_config: Option<PyPipelineConfig>,
    branch_conditions: Option<HashMap<String, String>>,
    jump_types: Option<Vec<String>>,
) -> PyResult<bool> {
    let hazards = {
        let mut analyzer = HazardAnalyzer::new(&graph.inner, pc_name);
        analyzer.identify_pipeline_stages();
        let h = analyzer.analyze_hazards();
        h.to_vec()
    };

    log::info!("Detected {} data hazard(s)", hazards.len());

    let gate_states = isa_states_to_gate.unwrap_or_else(|| vec!["pc_rd".to_string()]);
    let config = pipeline_config.map(|c| c.inner);

    let mut resolver = HazardResolver::new(&mut graph.inner, gate_states, config);

    let success = if !hazards.is_empty() {
        resolver.resolve_all_hazards(&hazards)
    } else {
        true
    };

    if let Some(ref bc) = branch_conditions {
        let jt = jump_types.unwrap_or_default();
        resolver.add_control_hazard_handling(bc, &jt, None);
    }

    resolver.gate_write_enables_with_validity();

    Ok(success)
}

// ===========================================================================
// Multi-cycle operations
// ===========================================================================

/// Set a memory to variable latency.
#[pyfunction]
#[pyo3(signature = (graph, memory_name, enable=true, min_latency=1, max_latency=1))]
fn set_memory_variable_latency(
    graph: &mut PyResourceGraph,
    memory_name: &str,
    enable: bool,
    min_latency: i64,
    max_latency: i64,
) -> bool {
    multi_cycle_ops::set_memory_variable_latency(&mut graph.inner, memory_name, enable, min_latency, max_latency)
}

/// Wire the start signal for a variable latency memory.
#[pyfunction]
fn wire_memory_start_signal(graph: &mut PyResourceGraph, memory_name: &str) -> bool {
    multi_cycle_ops::wire_memory_start_signal(&mut graph.inner, memory_name)
}

// ===========================================================================
// Branch prediction
// ===========================================================================

/// Apply not-taken branch prediction to a resource graph.
#[pyfunction]
#[pyo3(signature = (graph, pc_node_id=None, pc_mux_id=None, not_taken_input_id=None, taken_input_id=None))]
fn apply_branch_prediction_not_taken(
    graph: &mut PyResourceGraph,
    pc_node_id: Option<&str>,
    pc_mux_id: Option<&str>,
    not_taken_input_id: Option<&str>,
    taken_input_id: Option<&str>,
) -> bool {
    branch_prediction::apply_branch_prediction_not_taken(
        &mut graph.inner,
        pc_node_id,
        pc_mux_id,
        not_taken_input_id,
        taken_input_id,
    )
}

// ===========================================================================
// Branch Target Buffer
// ===========================================================================

/// Apply branch target buffer optimization to a resource graph.
#[pyfunction]
#[pyo3(signature = (graph, branch_enable_nodes, branch_outcome_node, branch_target_node, fetch_pc_node, branch_pc_node, predicted_pc_node_id, default_prediction_node_id, control_hazard_flush_node_id, num_entries=64, pc_width=32))]
fn apply_branch_target_buffer(
    graph: &mut PyResourceGraph,
    branch_enable_nodes: Vec<String>,
    branch_outcome_node: &str,
    branch_target_node: &str,
    fetch_pc_node: &str,
    branch_pc_node: &str,
    predicted_pc_node_id: &str,
    default_prediction_node_id: &str,
    control_hazard_flush_node_id: &str,
    num_entries: usize,
    pc_width: usize,
) -> bool {
    let mut spec = match branch_target_buffer::BTBSpec::new(
        branch_enable_nodes, branch_outcome_node, branch_target_node,
        fetch_pc_node, branch_pc_node, predicted_pc_node_id,
        default_prediction_node_id, control_hazard_flush_node_id,
    ) {
        Ok(s) => s,
        Err(e) => {
            log::error!("BTB spec error: {}", e);
            return false;
        }
    };
    spec.num_entries = num_entries;
    spec.pc_width = pc_width;
    branch_target_buffer::apply_branch_target_buffer(&mut graph.inner, spec)
}

// ===========================================================================
// Return Address Stack
// ===========================================================================

/// Apply return address stack optimization to a resource graph.
#[pyfunction]
#[pyo3(signature = (graph, call_enables, call_dest_regs, call_return_addrs, return_enables, return_src_regs, return_dest_regs, predicted_pc_node_id, default_prediction_node_id, control_hazard_flush_node_id, jalr_target_node_id, link_registers=None, ras_depth=8, ras_width=32, jalr_execute_enable_node_id=None, return_branch_taken_node_id=None, use_combinational_validity=false))]
fn apply_return_address_stack(
    graph: &mut PyResourceGraph,
    call_enables: Vec<String>,
    call_dest_regs: Vec<Option<String>>,
    call_return_addrs: Vec<String>,
    return_enables: Vec<String>,
    return_src_regs: Vec<Option<String>>,
    return_dest_regs: Vec<Option<String>>,
    predicted_pc_node_id: &str,
    default_prediction_node_id: &str,
    control_hazard_flush_node_id: &str,
    jalr_target_node_id: &str,
    link_registers: Option<Vec<i64>>,
    ras_depth: usize,
    ras_width: i64,
    jalr_execute_enable_node_id: Option<String>,
    return_branch_taken_node_id: Option<String>,
    use_combinational_validity: bool,
) -> bool {
    let call_specs: Vec<return_address_stack::CallSpec> = call_enables.into_iter()
        .zip(call_dest_regs.into_iter().zip(call_return_addrs.into_iter()))
        .map(|(enable, (dest, ret_addr))| return_address_stack::CallSpec {
            enable_node_id: enable,
            dest_reg_node_id: dest,
            return_addr_node_id: ret_addr,
        })
        .collect();
    let return_specs: Vec<return_address_stack::ReturnSpec> = return_enables.into_iter()
        .zip(return_src_regs.into_iter().zip(return_dest_regs.into_iter()))
        .map(|(enable, (src, dest))| return_address_stack::ReturnSpec {
            enable_node_id: enable,
            src_reg_node_id: src,
            dest_reg_node_id: dest,
        })
        .collect();
    let spec = return_address_stack::RASSpec {
        call_specs,
        return_specs,
        link_registers: link_registers.unwrap_or_else(|| vec![1, 5]),
        ras_depth,
        ras_width: ras_width as usize,
        predicted_pc_node_id: predicted_pc_node_id.to_string(),
        default_prediction_node_id: default_prediction_node_id.to_string(),
        control_hazard_flush_node_id: control_hazard_flush_node_id.to_string(),
        jalr_target_node_id: jalr_target_node_id.to_string(),
        jalr_execute_enable_node_id,
        return_branch_taken_node_id,
        use_combinational_validity,
    };
    return_address_stack::apply_return_address_stack(&mut graph.inner, spec)
}

// ===========================================================================
// Register Renaming
// ===========================================================================

/// Apply register renaming optimization to a resource graph.
#[pyfunction]
#[pyo3(signature = (graph, resource_name, num_physical_regs, target_indices=None, separate_regfiles=true, expand_rf=false))]
fn apply_register_renaming(
    graph: &mut PyResourceGraph,
    resource_name: &str,
    num_physical_regs: u32,
    target_indices: Option<Vec<String>>,
    separate_regfiles: bool,
    expand_rf: bool,
) -> bool {
    let spec = match register_renaming::RegisterRenamingSpec::new(
        resource_name, num_physical_regs, target_indices, separate_regfiles, expand_rf,
    ) {
        Ok(s) => s,
        Err(e) => {
            log::error!("Register renaming spec error: {}", e);
            return false;
        }
    };
    register_renaming::apply_register_renaming(&mut graph.inner, &spec)
}

// ===========================================================================
// Cache optimization
// ===========================================================================

/// Apply read-only cache optimization (e.g., instruction cache).
#[pyfunction]
#[pyo3(signature = (graph, memory_name, block_size=32, associativity=1, num_rows=64, address_width=32, data_width=None, cache_name=None, replacement_policy="lru", cached_ports=None))]
fn apply_read_only_cache(
    graph: &mut PyResourceGraph,
    memory_name: &str,
    block_size: usize,
    associativity: usize,
    num_rows: usize,
    address_width: usize,
    data_width: Option<usize>,
    cache_name: Option<String>,
    replacement_policy: &str,
    cached_ports: Option<Vec<String>>,
) -> PyResult<bool> {
    let mut spec = cache_optimization::ReadOnlyCacheSpec::new(memory_name);
    spec.block_size = block_size;
    spec.associativity = associativity;
    spec.num_rows = num_rows;
    spec.address_width = address_width;
    spec.data_width = data_width;
    if let Some(name) = cache_name {
        spec.cache_name = name;
    }
    spec.replacement_policy = replacement_policy.to_string();
    spec.cached_ports = cached_ports;
    Ok(cache_optimization::apply_read_only_cache(&mut graph.inner, &mut spec))
}

/// Apply read-write cache optimization (e.g., data cache).
#[pyfunction]
#[pyo3(signature = (graph, memory_name, block_size=32, associativity=1, num_rows=64, address_width=32, data_width=None, cache_name=None, replacement_policy="lru", cached_read_ports=None, cached_write_ports=None, write_allocate=false, write_read_fwd=false))]
fn apply_read_write_cache(
    graph: &mut PyResourceGraph,
    memory_name: &str,
    block_size: usize,
    associativity: usize,
    num_rows: usize,
    address_width: usize,
    data_width: Option<usize>,
    cache_name: Option<String>,
    replacement_policy: &str,
    cached_read_ports: Option<Vec<String>>,
    cached_write_ports: Option<Vec<String>>,
    write_allocate: bool,
    write_read_fwd: bool,
) -> PyResult<bool> {
    let mut spec = cache_optimization::ReadWriteCacheSpec::new(memory_name);
    spec.block_size = block_size;
    spec.associativity = associativity;
    spec.num_rows = num_rows;
    spec.address_width = address_width;
    spec.data_width = data_width;
    if let Some(name) = cache_name {
        spec.cache_name = name;
    }
    spec.replacement_policy = replacement_policy.to_string();
    spec.cached_read_ports = cached_read_ports;
    spec.cached_write_ports = cached_write_ports;
    spec.write_allocate = write_allocate;
    spec.write_read_fwd = write_read_fwd;
    Ok(cache_optimization::apply_read_write_cache(&mut graph.inner, &mut spec))
}

/// Wire cache start signal for a read-only cache.
#[pyfunction]
fn wire_cache_start_signal(graph: &mut PyResourceGraph, cache_name: &str) -> bool {
    cache_optimization::wire_cache_start_signal(&mut graph.inner, cache_name)
}

/// Wire cache start signal for a read-write cache.
#[pyfunction]
fn wire_rwcache_start_signal(graph: &mut PyResourceGraph, cache_name: &str) -> bool {
    cache_optimization::wire_rwcache_start_signal(&mut graph.inner, cache_name)
}

/// Add cache latency stalls for a read-only cache.
#[pyfunction]
#[pyo3(signature = (graph, cache_name, stage_name=None))]
fn add_cache_latency_stalls(graph: &mut PyResourceGraph, cache_name: &str, stage_name: Option<&str>) -> bool {
    cache_optimization::add_cache_latency_stalls(&mut graph.inner, cache_name, stage_name)
}

/// Add cache latency stalls for a read-write cache.
#[pyfunction]
#[pyo3(signature = (graph, cache_name, stage_name=None))]
fn add_rwcache_latency_stalls(graph: &mut PyResourceGraph, cache_name: &str, stage_name: Option<&str>) -> bool {
    cache_optimization::add_rwcache_latency_stalls(&mut graph.inner, cache_name, stage_name)
}

/// Connect a read-only cache's refill port to external memory.
#[pyfunction]
fn connect_cache_refill_to_memory(graph: &mut PyResourceGraph, cache_name: &str, memory_name: &str) -> bool {
    cache_optimization::connect_cache_refill_to_memory(&mut graph.inner, cache_name, memory_name)
}

/// Connect a read-write cache's write-through port to external memory.
#[pyfunction]
fn connect_rwcache_write_through(graph: &mut PyResourceGraph, cache_name: &str, memory_name: &str) -> bool {
    cache_optimization::connect_rwcache_write_through(&mut graph.inner, cache_name, memory_name)
}

/// Add a memory access arbiter for multiple memory nodes.
#[pyfunction]
fn add_memory_access_arbiter(graph: &mut PyResourceGraph, memories: Vec<String>) -> bool {
    cache_optimization::add_memory_access_arbiter(&mut graph.inner, &memories)
}

/// Clean up unreferenced flush placeholders.
#[pyfunction]
fn cleanup_unreferenced_flush_placeholders(graph: &mut PyResourceGraph) -> usize {
    cache_optimization::cleanup_unreferenced_flush_placeholders(&mut graph.inner)
}

// ===========================================================================
// Graph utility functions
// ===========================================================================

/// Infer uarch_time on a resource graph.
#[pyfunction]
#[pyo3(signature = (graph, force_reinfer=false))]
fn infer_uarch_time(graph: &mut PyResourceGraph, force_reinfer: bool) {
    graph.inner.infer_uarch_time(force_reinfer);
}

/// Infer pipe_time on a resource graph.
#[pyfunction]
#[pyo3(signature = (graph, force_reinfer=false))]
fn infer_pipe_time(graph: &mut PyResourceGraph, force_reinfer: bool) {
    graph.inner.infer_pipe_time(force_reinfer);
}

// ===========================================================================
// JSON ↔ Python helpers
// ===========================================================================

/// Convert a serde_json::Value to a Python object.
fn json_value_to_py(py: Python<'_>, val: &Value) -> PyResult<PyObject> {
    use pyo3::ToPyObject;
    match val {
        Value::Null => Ok(py.None()),
        Value::Bool(b) => Ok(b.to_object(py)),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Ok(i.to_object(py))
            } else if let Some(f) = n.as_f64() {
                Ok(f.to_object(py))
            } else {
                Ok(py.None())
            }
        }
        Value::String(s) => Ok(s.to_object(py)),
        Value::Array(arr) => {
            let items: Vec<PyObject> = arr
                .iter()
                .map(|v| json_value_to_py(py, v))
                .collect::<PyResult<_>>()?;
            Ok(items.to_object(py))
        }
        Value::Object(map) => {
            let dict = pyo3::types::PyDict::new_bound(py);
            for (k, v) in map {
                dict.set_item(k, json_value_to_py(py, v)?)?;
            }
            Ok(dict.into_any().unbind())
        }
    }
}

/// Convert a Python object to a serde_json::Value.
fn py_to_json_value(obj: PyObject, py: Python<'_>) -> PyResult<Value> {
    use pyo3::types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyString};

    let bound = obj.bind(py);
    if bound.is_none() {
        Ok(Value::Null)
    } else if let Ok(b) = bound.downcast::<PyBool>() {
        Ok(Value::Bool(b.is_true()))
    } else if let Ok(i) = bound.downcast::<PyInt>() {
        let val: i64 = i.extract()?;
        Ok(json!(val))
    } else if let Ok(f) = bound.downcast::<PyFloat>() {
        let val: f64 = f.extract()?;
        Ok(json!(val))
    } else if let Ok(s) = bound.downcast::<PyString>() {
        let val: String = s.extract()?;
        Ok(Value::String(val))
    } else if let Ok(list) = bound.downcast::<PyList>() {
        let items: Vec<Value> = list.iter()
            .map(|item| py_to_json_value(item.unbind(), py))
            .collect::<PyResult<_>>()?;
        Ok(Value::Array(items))
    } else if let Ok(dict) = bound.downcast::<PyDict>() {
        let mut map = serde_json::Map::new();
        for (k, v) in dict.iter() {
            let key: String = k.extract()?;
            let val = py_to_json_value(v.unbind(), py)?;
            map.insert(key, val);
        }
        Ok(Value::Object(map))
    } else {
        // Fallback: try string representation
        let s: String = bound.str()?.extract()?;
        Ok(Value::String(s))
    }
}

// ===========================================================================
// Module registration
// ===========================================================================

/// The isacomp_core Python module.
#[pymodule]
pub fn isacomp_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Route Rust log messages to Python's logging module
    pyo3_log::init();

    // Core types
    m.add_class::<PyResourceGraph>()?;
    m.add_class::<PyNode>()?;
    m.add_class::<PyEdge>()?;
    m.add_class::<PyISAParser>()?;
    m.add_class::<PyVerilogGenerator>()?;
    m.add_class::<PyMemoryAccessTransformSpec>()?;
    m.add_class::<PyMemoryAccessTransform>()?;
    m.add_class::<PyPipelineConfig>()?;
    m.add_class::<PyPipelineCut>()?;
    m.add_class::<PyEdgeEndpoint>()?;

    // Merge & memory
    m.add_function(wrap_pyfunction!(merge_instructions, m)?)?;
    m.add_function(wrap_pyfunction!(apply_memory_externalization, m)?)?;

    // Pipeline
    m.add_class::<PyPipelineTransform>()?;
    m.add_function(wrap_pyfunction!(get_pipeline_config, m)?)?;
    m.add_function(wrap_pyfunction!(apply_pipeline_transforms, m)?)?;
    m.add_function(wrap_pyfunction!(get_pipeline_summary, m)?)?;

    // Hazard resolution
    m.add_class::<PyHazardResolutionStrategy>()?;
    m.add_class::<PyHazardAnalyzer>()?;
    m.add_class::<PyHazardResolver>()?;
    m.add_function(wrap_pyfunction!(apply_hazard_resolution, m)?)?;

    // Multi-cycle operations
    m.add_function(wrap_pyfunction!(set_memory_variable_latency, m)?)?;
    m.add_function(wrap_pyfunction!(wire_memory_start_signal, m)?)?;

    // Branch prediction
    m.add_function(wrap_pyfunction!(apply_branch_prediction_not_taken, m)?)?;

    // Branch target buffer
    m.add_function(wrap_pyfunction!(apply_branch_target_buffer, m)?)?;

    // Return address stack
    m.add_function(wrap_pyfunction!(apply_return_address_stack, m)?)?;

    // Register renaming
    m.add_function(wrap_pyfunction!(apply_register_renaming, m)?)?;

    // Cache optimization
    m.add_function(wrap_pyfunction!(apply_read_only_cache, m)?)?;
    m.add_function(wrap_pyfunction!(apply_read_write_cache, m)?)?;
    m.add_function(wrap_pyfunction!(wire_cache_start_signal, m)?)?;
    m.add_function(wrap_pyfunction!(wire_rwcache_start_signal, m)?)?;
    m.add_function(wrap_pyfunction!(add_cache_latency_stalls, m)?)?;
    m.add_function(wrap_pyfunction!(add_rwcache_latency_stalls, m)?)?;
    m.add_function(wrap_pyfunction!(connect_cache_refill_to_memory, m)?)?;
    m.add_function(wrap_pyfunction!(connect_rwcache_write_through, m)?)?;
    m.add_function(wrap_pyfunction!(add_memory_access_arbiter, m)?)?;
    m.add_function(wrap_pyfunction!(cleanup_unreferenced_flush_placeholders, m)?)?;

    // Graph utilities
    m.add_function(wrap_pyfunction!(infer_uarch_time, m)?)?;
    m.add_function(wrap_pyfunction!(infer_pipe_time, m)?)?;

    Ok(())
}
