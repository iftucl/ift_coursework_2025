Pipeline C — Factor Computation
=================================

Pipeline C loads structured data from PostgreSQL, computes the 8-metric
Value + Quality composite factor scores, and writes results back to the
database.

Data Loader
-----------

.. automodule:: modules.db_loader.data_loader
   :members:
   :undoc-members:
   :show-inheritance:

Factor Model
------------

.. automodule:: modules.factor.factor_model
   :members:
   :undoc-members:
   :show-inheritance:

Factor Writer
-------------

.. automodule:: modules.db_writer.factor_writer
   :members:
   :undoc-members:
   :show-inheritance:
