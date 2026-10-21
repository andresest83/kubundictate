"""Makes the pip-installed CUDA libraries findable on Windows.

The nvidia-*-cu12 pip packages (cublas, cudnn, cufft, ...) ship their DLLs
under nvidia/<pkg>/bin on Windows (unlike the lib/ layout on Linux).
ctranslate2 and onnxruntime resolve them via plain LoadLibrary, which only
honors PATH -- adding them via os.add_dll_directory alone is not enough.
Every package's bin/ is added, so an engine that needs one more CUDA library
only needs it pip-installed. Must run before the engine is imported. Not
needed for torch, which bundles its own.
"""

import os


def add_to_path() -> None:
    try:
        import nvidia
    except ImportError:
        return
    bins = []
    for root in nvidia.__path__:
        for pkg in sorted(os.listdir(root)):
            bin_dir = os.path.join(root, pkg, "bin")
            if os.path.isdir(bin_dir):
                bins.append(bin_dir)
    if bins:
        os.environ["PATH"] = os.pathsep.join(bins) + os.pathsep + os.environ["PATH"]
