from setuptools import setup, find_packages

setup(
    name='egfet-experiment-controls',
    version='1.0.0',
    packages=find_packages('src'),
    package_dir={'': 'src'},
    package_data={
        "views.qt.ui_files": ["src/views/qt/ui_files/**/*.ui"]
    },
    entry_points={
        'console_scripts': [
            'LabCon = views.gui:main',
            'LabConCli = views.cli:cli'
        ]
    },
)