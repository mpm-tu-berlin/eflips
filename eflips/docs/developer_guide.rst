Developer's Guide
=================

Installing eFLIPS as a GIT submodule
------------------------------------

If you are actively involved in eFLIPS development, you will most likely face the following usage scenario:

#. You are working in your own GIT repository containing scripts for your simulation activities.
#. You wish to use the package ``eflips`` as well as any packages containing operator-specific I/O functions in your scripts, using a simple ``import eflips`` statement.
#. You wish to be able to modify ``eflips`` code from within your GIT repository folder, i.e. without switching between several project environments.
#. You wish to be able to pull and push ``eflips`` code from/to the 'proper' repository at ``https://github.com/mpm-tu-berlin/eflips``.

