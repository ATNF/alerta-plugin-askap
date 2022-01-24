
from setuptools import setup, find_packages

version = '1.0.2'

setup(
    name="alerta-askap",
    version=version,
    description='Modify incomming Alerts for ASKAP',
    url='https://github.com/atnf/alerta-plugin-askap',
    license='MIT',
    author='Craig Haskins',
    author_email='Craig.Haskins@csiro.au',
    packages=find_packages(),
    py_modules=['alerta_askap'],
    include_package_data=True,
    zip_safe=True,
    entry_points={
        'alerta.plugins': [
            'askap = alerta_askap:ServiceIntegration'
        ]
    }
)
