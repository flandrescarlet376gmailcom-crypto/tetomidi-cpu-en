"""
Fast CPU runtime helpers for tetomidi.

- physical_cores(): number of real CPU cores (not hyper-threads).
- thread_count(setting): thread count from the user setting ("auto" or a number).
- make_session(path): ONNX Runtime session tuned for CPU inference.
- run_model(session, feeds): run the model and return outputs.

Only standard library + optional psutil/onnxruntime. Nothing here depends on
the Transkun source, so it is safe to keep even before the export is ready.
"""
import os

try:
    import psutil
except ImportError:  # psutil is optional
    psutil = None

try:
    import onnxruntime as ort
except ImportError:  # onnxruntime is optional until the ONNX model is ready
    ort = None


def physical_cores():
    """Real CPU cores. Falls back to half of the logical count."""
    if psutil is not None:
        n = psutil.cpu_count(logical=False)
        if n:
            return n
    logical = os.cpu_count() or 2
    return max(1, logical // 2)


def thread_count(setting="auto"):
    """
    setting: "auto" or an integer (as string or int).
    auto -> all physical cores. Manual values are clamped to 1..logical cores.
    """
    logical = os.cpu_count() or 2
    if str(setting).lower() == "auto":
        return physical_cores()
    try:
        n = int(setting)
    except (TypeError, ValueError):
        return physical_cores()
    return max(1, min(n, logical))


def make_session(model_path, threads="auto"):
    """Create an ONNX Runtime session that uses the chosen number of cores."""
    if ort is None:
        raise RuntimeError("onnxruntime is not installed")
    n = thread_count(threads)
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = n          # threads used inside one operator
    opts.inter_op_num_threads = 1          # run operators one after another
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    opts.enable_mem_pattern = True
    opts.enable_cpu_mem_arena = True
    return ort.InferenceSession(model_path, sess_options=opts,
                                providers=["CPUExecutionProvider"])


def run_model(session, feeds):
    """feeds: dict of input name -> numpy array. Returns list of outputs."""
    return session.run(None, feeds)
