pub mod adapter;
pub mod integration;
pub mod mock;
pub mod model;
pub mod provider;
pub mod python_sidecar;
pub mod registry;
pub mod service;

pub use adapter::EmbeddingAdapter;
pub use integration::VectorIngestService;
pub use mock::DeterministicEmbeddingProvider;
pub use model::*;
pub use provider::EmbeddingProvider;
pub use python_sidecar::{PythonSidecarEmbeddingProvider, supported_sidecar_models};
pub use registry::EmbeddingRegistry;
pub use service::{EmbeddingServiceManager, EmbeddingServiceStatus};
