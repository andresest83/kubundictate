"""Makes the pip-installed CUDA libraries findable on Windows.

The nvidia-cublas-cu12/nvidia-cudnn-cu12 pip packages ship their DLLs
under <pkg>/bin on Windows (unlike the lib/ layout on Linux). ctranslate2
and onnxruntime resolve them via plain LoadLibrary, which only honors
PATH -- adding them via os.add_dll_directory alone is not enough. Must run
before the engine is imported. Not needed for torch, which bundles its own.
"""

import os


def add_to_path() -> None:
    try:
        import nvidia.cublas
        import nvidia.cudnn
    except ImportError:
        return
    cublas_bin = os.path.join(list(nvidia.cublas.__path__)[0], "bin")
    cudnn_bin = os.path.join(list(nvidia.cudnn.__path__)[0], "bin")
    os.environ["PATH"] = cublas_bin + os.pathsep + cudnn_bin + os.pathsep + os.environ["PATH"]
