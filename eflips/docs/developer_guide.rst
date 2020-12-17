Developer's Guide
=================

Installing eFLIPS as a GIT submodule
------------------------------------

If you are actively involved in eFLIPS development, you will most likely face the following usage scenario:

#. You are working in your own GIT repository containing scripts for your simulation activities.
#. You wish to use the package ``eflips`` as well as any other packages containing operator-specific functionality in your scripts, using simple ``import xyz`` statements.
#. You wish to be able to modify ``eflips`` code from within your main IDE project environment, i.e. without switching between several project environments.
#. You wish to be able to pull and push ``eflips`` code from/to the 'proper' repository at ``https://github.com/mpm-tu-berlin/eflips``.

We can achieve this using a combination of GIT submodules and symbolic links (symlinks). The following tutorial walks you through creating a GIT repository of your own, configuring ``eflips`` as a submodule and creating symbolic links to include it in the module search path.

First, if using Windows 10, make sure to enable Developer Mode in *Settings > For Developers > Developer Mode*:

.. figure:: img/developer_guide/win10_developer_mode.png
    :alt: Enabling developer mode in Windows 10

    Enabling developer mode in Windows 10

Otherwise, you will require admin privileges to create symlinks.

Now, create a GIT repository on your platform of choice. For this example, we use TU Berlin's GitLab service to create a ``test-project``. Make a local clone of the project **and enable symlink support**:

.. code-block:: none

    D:\GIT> git clone --config core.symlinks=true <url_to_repository>

Add a ``.gitignore`` file to the newly created folder. This modified GitHub template works perfectly for us:

.. code-block:: none

    # Byte-compiled / optimized / DLL files
    **/__pycache__/
    *.py[cod]
    *$py.class

    # C extensions
    *.so

    # Distribution / packaging
    .Python
    build/
    develop-eggs/
    dist/
    downloads/
    eggs/
    .eggs/
    lib/
    lib64/
    parts/
    sdist/
    var/
    wheels/
    pip-wheel-metadata/
    share/python-wheels/
    *.egg-info/
    .installed.cfg
    *.egg
    MANIFEST

    # PyInstaller
    #  Usually these files are written by a python script from a template
    #  before PyInstaller builds the exe, so as to inject date/other infos into it.
    *.manifest
    *.spec

    # Installer logs
    pip-log.txt
    pip-delete-this-directory.txt

    # Unit test / coverage reports
    **/htmlcov/
    **/.tox/
    **/.nox/
    .coverage
    .coverage.*
    .cache
    nosetests.xml
    coverage.xml
    *.cover
    *.py,cover
    **/.hypothesis/
    **/.pytest_cache/

    # Translations
    *.mo
    *.pot

    # Django stuff:
    *.log
    local_settings.py
    db.sqlite3
    db.sqlite3-journal

    # Flask stuff:
    **/instance/
    .webassets-cache

    # Scrapy stuff:
    .scrapy

    # Sphinx documentation
    **/docs/_build/

    # PyBuilder
    **/target/

    # Jupyter Notebook
    .ipynb_checkpoints

    # IPython
    **/profile_default/
    ipython_config.py

    # pyenv
    .python-version

    # pipenv
    #   According to pypa/pipenv#598, it is recommended to include Pipfile.lock in version control.
    #   However, in case of collaboration, if having platform-specific dependencies or dependencies
    #   having no cross-platform support, pipenv may install dependencies that don't work, or not
    #   install all needed dependencies.
    #Pipfile.lock

    # PEP 582; used by e.g. github.com/David-OConnor/pyflow
    **/__pypackages__/

    # Celery stuff
    celerybeat-schedule
    celerybeat.pid

    # SageMath parsed files
    *.sage.py

    # Environments
    .env
    .venv
    **/env/
    **/venv/
    **/ENV/
    **/env.bak/
    **/venv.bak/

    # Spyder project settings
    .spyderproject
    .spyproject

    # Rope project settings
    .ropeproject

    # mkdocs documentation
    /site

    # mypy
    **/.mypy_cache/
    .dmypy.json
    dmypy.json

    # Pyre type checker
    **/.pyre/

    # PyCharm
    **/.idea/

    # eflips build script
    build_wheel.bat

Commit and push:

.. code-block:: none

    D:\GIT\test-project> git add .
    D:\GIT\test-project> git commit -m "Initial commit"
    D:\GIT\test-project> git push -u origin master

If you already have a GIT repository, you can enable symlink support by editing the ``.git/config`` file to include:

.. code-block:: none

    [core]
        symlinks = true

Now, include ``eflips`` as a GIT submodule in your own repository, **but be sure to clone it into an** ``eflips-git`` **folder**:

.. code-block:: none

    D:\GIT\test-project> git submodule add https://github.com/mpm-tu-berlin/eflips.git eflips-git

You may notice the ``eflips`` package is now found in the ``test-project/eflips-git/eflips`` folder. However, we want it to appear on the top level, otherwise it won't be within the module search path (unless we fiddle around with ``sys.path.append()`` at the top of every script - no thanks...). This is where symbolic links come into play. Create a **relative** symlink using:

.. code-block:: none

    D:\GIT\test-project> mklink /D eflips "eflips-git\eflips"

If you now create a project in your favourite IDE with ``test-project`` as the root folder, opening a console and typing

.. code-block:: none

    import eflips

should yield success, provided you have installed all dependencies into your Python environment. A ``requirements.txt`` file is provided for this. Assuming you have installed a Python virtual environment into a ``venv`` subfolder in your repository, invoke:

.. code-block:: none

    D:\GIT\test-project\venv\Scripts> pip install -r ..\..\eflips\requirements.txt


.. code-block:: none

    C:\Program Files\Python38> python -m venv "D:\GIT\test-project\venv"