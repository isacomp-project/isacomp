//! Pipeline configuration for processors.
//!
//! Defines pipeline stage configurations for 2, 3, 4, or 5-stage pipelines.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// A pipeline cut (boundary between stages).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PipelineCut {
    /// Name of the stage AFTER the cut
    pub name: String,
    pub description: String,
    /// 0-indexed position in the pipeline
    pub stage_index: usize,
}

/// Configuration for a pipelined processor.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PipelineConfig {
    pub num_stages: usize,
    pub stage_names: Vec<String>,
    pub cuts: Vec<PipelineCut>,
    pub register_read_stage: String,
    pub register_write_stage: String,
    pub memory_stage: String,
    pub branch_resolution_stage: String,
    pub prefix: String,
}

impl PipelineConfig {
    pub fn get_stage_index(&self, stage_name: &str) -> Option<usize> {
        self.stage_names.iter().position(|s| s == stage_name)
    }

    pub fn get_stage_name(&self, index: usize) -> Option<&str> {
        self.stage_names.get(index).map(|s| s.as_str())
    }

    pub fn get_cut_for_stage(&self, stage_name: &str) -> Option<&PipelineCut> {
        self.cuts.iter().find(|c| c.name == stage_name)
    }

    pub fn get_validity_signal_id(&self, stage_name: &str) -> String {
        format!("{}_{}_valid_{}", self.prefix, stage_name, self.prefix)
    }

    pub fn get_stall_controller_id(&self, stage_name: &str) -> String {
        format!("{}_{}_stall_ctrl", self.prefix, stage_name)
    }

    pub fn get_stages_before(&self, stage_name: &str) -> Vec<&str> {
        if let Some(idx) = self.get_stage_index(stage_name) {
            self.stage_names[..idx].iter().map(|s| s.as_str()).collect()
        } else {
            vec![]
        }
    }

    pub fn get_stages_after(&self, stage_name: &str) -> Vec<&str> {
        if let Some(idx) = self.get_stage_index(stage_name) {
            self.stage_names[idx + 1..].iter().map(|s| s.as_str()).collect()
        } else {
            vec![]
        }
    }

    pub fn get_hazard_stages(&self) -> Vec<&str> {
        let read_idx = self.get_stage_index(&self.register_read_stage).unwrap_or(0);
        let write_idx = self.get_stage_index(&self.register_write_stage).unwrap_or(self.stage_names.len() - 1);
        self.stage_names[read_idx..=write_idx].iter().map(|s| s.as_str()).collect()
    }
}

pub fn create_5_stage_config() -> PipelineConfig {
    PipelineConfig {
        num_stages: 5,
        stage_names: vec![
            "Fetch".into(), "Decode".into(), "Execute".into(),
            "Memory".into(), "Writeback".into(),
        ],
        cuts: vec![
            PipelineCut { name: "Decode".into(), description: "F/D boundary - instruction fetch complete".into(), stage_index: 1 },
            PipelineCut { name: "Execute".into(), description: "D/X boundary - decode complete".into(), stage_index: 2 },
            PipelineCut { name: "Memory".into(), description: "X/M boundary - execute complete".into(), stage_index: 3 },
            PipelineCut { name: "Writeback".into(), description: "M/W boundary - memory access complete".into(), stage_index: 4 },
        ],
        register_read_stage: "Decode".into(),
        register_write_stage: "Writeback".into(),
        memory_stage: "Memory".into(),
        branch_resolution_stage: "Execute".into(),
        prefix: "PIPE".into(),
    }
}

pub fn create_4_stage_config() -> PipelineConfig {
    PipelineConfig {
        num_stages: 4,
        stage_names: vec![
            "Fetch".into(), "Decode".into(), "Execute".into(),
            "MemoryWriteback".into(),
        ],
        cuts: vec![
            PipelineCut { name: "Decode".into(), description: "F/D boundary - instruction fetch complete".into(), stage_index: 1 },
            PipelineCut { name: "Execute".into(), description: "D/X boundary - decode complete".into(), stage_index: 2 },
            PipelineCut { name: "MemoryWriteback".into(), description: "X/MW boundary - execute complete".into(), stage_index: 3 },
        ],
        register_read_stage: "Decode".into(),
        register_write_stage: "MemoryWriteback".into(),
        memory_stage: "MemoryWriteback".into(),
        branch_resolution_stage: "Execute".into(),
        prefix: "PIPE".into(),
    }
}

pub fn create_3_stage_config() -> PipelineConfig {
    PipelineConfig {
        num_stages: 3,
        stage_names: vec![
            "Fetch".into(), "Decode".into(), "ExecuteMemoryWriteback".into(),
        ],
        cuts: vec![
            PipelineCut { name: "Decode".into(), description: "F/D boundary - instruction fetch complete".into(), stage_index: 1 },
            PipelineCut { name: "ExecuteMemoryWriteback".into(), description: "D/XMW boundary - decode complete".into(), stage_index: 2 },
        ],
        register_read_stage: "Decode".into(),
        register_write_stage: "ExecuteMemoryWriteback".into(),
        memory_stage: "ExecuteMemoryWriteback".into(),
        branch_resolution_stage: "ExecuteMemoryWriteback".into(),
        prefix: "PIPE".into(),
    }
}

pub fn create_2_stage_config() -> PipelineConfig {
    PipelineConfig {
        num_stages: 2,
        stage_names: vec![
            "FetchDecode".into(), "ExecuteMemoryWriteback".into(),
        ],
        cuts: vec![
            PipelineCut { name: "ExecuteMemoryWriteback".into(), description: "FD/XMW boundary - decode complete".into(), stage_index: 1 },
        ],
        register_read_stage: "FetchDecode".into(),
        register_write_stage: "ExecuteMemoryWriteback".into(),
        memory_stage: "ExecuteMemoryWriteback".into(),
        branch_resolution_stage: "ExecuteMemoryWriteback".into(),
        prefix: "PIPE".into(),
    }
}

pub fn get_pipeline_config(num_stages: usize) -> Result<PipelineConfig, String> {
    match num_stages {
        2 => Ok(create_2_stage_config()),
        3 => Ok(create_3_stage_config()),
        4 => Ok(create_4_stage_config()),
        5 => Ok(create_5_stage_config()),
        _ => Err(format!("Unsupported number of stages: {}. Supported: 2, 3, 4, or 5", num_stages)),
    }
}

/// Maps between different pipeline configurations.
pub struct PipelineStageMapper {
    config: PipelineConfig,
    canonical_to_actual: HashMap<String, String>,
    actual_to_canonical: HashMap<String, String>,
}

const CANONICAL_STAGES: &[&str] = &["Fetch", "Decode", "Execute", "Memory", "Writeback"];

impl PipelineStageMapper {
    pub fn new(config: PipelineConfig) -> Self {
        let (c2a, a2c) = Self::build_mappings(&config);
        Self {
            config,
            canonical_to_actual: c2a,
            actual_to_canonical: a2c,
        }
    }

    fn build_mappings(config: &PipelineConfig) -> (HashMap<String, String>, HashMap<String, String>) {
        let mut c2a = HashMap::new();
        let mut a2c = HashMap::new();

        match config.num_stages {
            5 => {
                for &s in CANONICAL_STAGES {
                    c2a.insert(s.to_string(), s.to_string());
                    a2c.insert(s.to_string(), s.to_string());
                }
            }
            4 => {
                for &(canonical, actual) in &[
                    ("Fetch", "Fetch"), ("Decode", "Decode"), ("Execute", "Execute"),
                    ("Memory", "MemoryWriteback"), ("Writeback", "MemoryWriteback"),
                ] {
                    c2a.insert(canonical.into(), actual.into());
                }
                for &(actual, canonical) in &[
                    ("Fetch", "Fetch"), ("Decode", "Decode"), ("Execute", "Execute"),
                    ("MemoryWriteback", "Writeback"),
                ] {
                    a2c.insert(actual.into(), canonical.into());
                }
            }
            3 => {
                for &(canonical, actual) in &[
                    ("Fetch", "Fetch"), ("Decode", "Decode"),
                    ("Execute", "ExecuteMemoryWriteback"),
                    ("Memory", "ExecuteMemoryWriteback"),
                    ("Writeback", "ExecuteMemoryWriteback"),
                ] {
                    c2a.insert(canonical.into(), actual.into());
                }
                for &(actual, canonical) in &[
                    ("Fetch", "Fetch"), ("Decode", "Decode"),
                    ("ExecuteMemoryWriteback", "Writeback"),
                ] {
                    a2c.insert(actual.into(), canonical.into());
                }
            }
            2 => {
                for &(canonical, actual) in &[
                    ("Fetch", "FetchDecode"), ("Decode", "FetchDecode"),
                    ("Execute", "ExecuteMemoryWriteback"),
                    ("Memory", "ExecuteMemoryWriteback"),
                    ("Writeback", "ExecuteMemoryWriteback"),
                ] {
                    c2a.insert(canonical.into(), actual.into());
                }
                for &(actual, canonical) in &[
                    ("FetchDecode", "Decode"),
                    ("ExecuteMemoryWriteback", "Writeback"),
                ] {
                    a2c.insert(actual.into(), canonical.into());
                }
            }
            _ => {}
        }

        (c2a, a2c)
    }

    pub fn canonical_to_actual<'a>(&'a self, canonical_stage: &'a str) -> &'a str {
        self.canonical_to_actual.get(canonical_stage)
            .map(|s| s.as_str())
            .unwrap_or(canonical_stage)
    }

    pub fn actual_to_canonical<'a>(&'a self, actual_stage: &'a str) -> &'a str {
        self.actual_to_canonical.get(actual_stage)
            .map(|s| s.as_str())
            .unwrap_or(actual_stage)
    }

    pub fn get_pipeline_register_prefix(&self, canonical_stage: &str) -> String {
        let actual = self.canonical_to_actual(canonical_stage);
        format!("{}_{}_", self.config.prefix, actual)
    }

    pub fn config(&self) -> &PipelineConfig {
        &self.config
    }
}

/// Parse the stage name from a pipeline register ID.
pub fn parse_stage_from_register_id(register_id: &str, prefix: &str) -> Option<String> {
    let pfx = format!("{}_", prefix);
    let sfx = format!("_{}", prefix);
    if !register_id.starts_with(&pfx) || !register_id.ends_with(&sfx) {
        return None;
    }
    // Strip both the prefix and suffix to isolate the core portion.
    let core = &register_id[pfx.len()..register_id.len() - sfx.len()];
    core.split('_').next().map(|s| s.to_string())
}

/// Count the pipeline depth by counting trailing _PIPE suffixes.
pub fn count_pipeline_depth(register_id: &str, prefix: &str) -> usize {
    let suffix = format!("_{}", prefix);
    let mut depth = 0;
    let mut temp = register_id;
    while temp.ends_with(&suffix) {
        depth += 1;
        temp = &temp[..temp.len() - suffix.len()];
    }
    depth
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_5_stage_config() {
        let config = create_5_stage_config();
        assert_eq!(config.num_stages, 5);
        assert_eq!(config.stage_names.len(), 5);
        assert_eq!(config.cuts.len(), 4);
        assert_eq!(config.get_stage_index("Fetch"), Some(0));
        assert_eq!(config.get_stage_index("Writeback"), Some(4));
    }

    #[test]
    fn test_get_pipeline_config() {
        for n in [2, 3, 4, 5] {
            let config = get_pipeline_config(n).unwrap();
            assert_eq!(config.num_stages, n);
        }
        assert!(get_pipeline_config(6).is_err());
    }

    #[test]
    fn test_stage_mapper() {
        let config = create_3_stage_config();
        let mapper = PipelineStageMapper::new(config);
        assert_eq!(mapper.canonical_to_actual("Execute"), "ExecuteMemoryWriteback");
        assert_eq!(mapper.actual_to_canonical("ExecuteMemoryWriteback"), "Writeback");
    }

    #[test]
    fn test_parse_stage_from_register_id() {
        assert_eq!(
            parse_stage_from_register_id("PIPE_Execute_add_res_PIPE", "PIPE"),
            Some("Execute".to_string())
        );
        assert_eq!(
            parse_stage_from_register_id("not_a_register", "PIPE"),
            None
        );
    }

    #[test]
    fn test_count_pipeline_depth() {
        assert_eq!(count_pipeline_depth("PIPE_Execute_rd_PIPE", "PIPE"), 1);
        assert_eq!(count_pipeline_depth("PIPE_Memory_PIPE_Execute_rd_PIPE_PIPE", "PIPE"), 2);
    }

    #[test]
    fn test_hazard_stages() {
        let config = create_5_stage_config();
        let stages = config.get_hazard_stages();
        assert_eq!(stages, vec!["Decode", "Execute", "Memory", "Writeback"]);
    }
}
