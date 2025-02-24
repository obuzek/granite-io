# SPDX-License-Identifier: Apache-2.0

__doc__ = f"""
The {__package__} library provides a common programming abstraction for using
the advanced control instructions with Granite models.
"""

# Local
from granite_io.backend import backend, make_backend  # noqa: F401
from granite_io.io import io_processor, make_io_processor  # noqa: F401
