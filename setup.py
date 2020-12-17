import setuptools

with open('README.md', 'r') as fh:
    long_description = fh.read()

setuptools.setup(
    name='eflips',
    version='0.0.1',
    author='D. Jefferies, P. Boev, E. Lauth',
    author_email='dominic.jefferies@tu-berlin.de',
    description='eFLIPS: Electric Fleet and Infrastructure Planning/Simulation',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/mpm-tu-berlin/eflips',
    packages=setuptools.find_packages(),
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    install_requires=[
        'pandas',
        'xlsxwriter',
        'requests',
        'numpy',
        'openpyxl',
        'simpy',
        'folium',
        'matplotlib'
    ],
    python_requires='>=3.7',
    package_data={
        'eflips': ['settings_default.json', 'requirements.txt']
    }
)
