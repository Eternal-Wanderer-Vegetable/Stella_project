use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;

mod policy;
mod promotion;
mod retrieval;
mod schema;
mod similarity;

#[pyfunction]
fn retrieve(request_json: &str) -> PyResult<String> {
    let request = serde_json::from_str(request_json)
        .map_err(|err| PyValueError::new_err(format!("invalid retrieval request: {err}")))?;
    let output = retrieval::retrieve(request).map_err(PyRuntimeError::new_err)?;
    serde_json::to_string(&output)
        .map_err(|err| PyRuntimeError::new_err(format!("retrieval serialization failed: {err}")))
}

#[pyfunction]
fn promote(request_json: &str) -> PyResult<String> {
    let request = serde_json::from_str(request_json)
        .map_err(|err| PyValueError::new_err(format!("invalid promotion request: {err}")))?;
    let output = promotion::promote(request).map_err(PyRuntimeError::new_err)?;
    serde_json::to_string(&output)
        .map_err(|err| PyRuntimeError::new_err(format!("promotion serialization failed: {err}")))
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("BACKEND_API_VERSION", schema::BACKEND_API_VERSION)?;
    module.add("MEMORY_SCHEMA_VERSION", schema::MEMORY_SCHEMA_VERSION)?;
    module.add_function(wrap_pyfunction!(retrieve, module)?)?;
    module.add_function(wrap_pyfunction!(promote, module)?)?;
    Ok(())
}
