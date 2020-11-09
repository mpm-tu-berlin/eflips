Installation
============

eFLIPS was tested with Python 3.8 and 3.7. It depends on various other packages declared in ``requirements.txt`` in the ``eflips`` folder. Please be aware that when using very new releases of Python, some packages containing binaries (especially ``matplotlib``) may require compilation as long as precompiled binaries for the respective Python release are not available. In this case, ``pip``, the package installer, will attempt to compile the binaries automatically, but this often causes problems in our experience. Should this happen, use an older version of Python.

We recommend using the standard Python installation from `python.org <https://www.python.org/>`_ and creating a virtual environment with `venv <https://docs.python.org/3/library/venv.html>`_, using, e.g.:

.. code-block:: none

    C:\Program Files\Python38> python -m venv "C:\Users\djefferies\venv_python38_eflips"

When working with virtual environments, it is important **not** to add Python to the system PATH, so be sure to choose the installation settings accordingly.

To install the packages required for ``eflips`` into the virtual environment, invoke:

.. code-block:: none

    C:\Users\djefferies\venv_python38_eflips\Scripts> pip install -r path_to_requirements_txt_file

If this produces errors like the following one, delete your virtual environment folder, uninstall Python and choose an older Python version:

.. code-block:: none

    error: Microsoft Visual C++ 14.0 is required. Get it with "Build Tools for Visual Studio":
    https://visualstudio.microsoft.com/downloads/

Once successfully installed, configure the interpreter settings in your IDE to use the ``python.exe`` in the ``Scripts`` directory of your virtual environment as the interpreter.

In your IDE, open a Python console and make sure the ``eflips`` folder's parent folder is within the module search path (usually, the IDE takes care of this if your project is correctly configured). To manually add a folder to the search path, enter:

.. code-block::

    import sys
    sys.path.append(path_to_folder)

If you can execute ``import eflips`` without any errors, you're ready to go!