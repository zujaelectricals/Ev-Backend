# Utils package for payout app
# Re-export functions from parent utils.py module to maintain backward compatibility
# This allows imports like "from .utils import process_payout" to work
# even though utils is now a package instead of a module

# Import from the parent package's utils module using importlib
# This works around the fact that we can't directly import utils.py when utils/ exists
import importlib.util
import os
import sys

# Get path to parent utils.py file
_current_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_current_dir)
_utils_file = os.path.join(_parent_dir, 'utils.py')

# Load utils.py as a module with proper package context
_spec = importlib.util.spec_from_file_location("core.payout.utils_module", _utils_file)
_payout_utils = importlib.util.module_from_spec(_spec)

# Set the package attribute so relative imports work
_payout_utils.__package__ = 'core.payout'
_payout_utils.__name__ = 'core.payout.utils_module'

# Add parent directory to path temporarily for imports
_parent_parent = os.path.dirname(_parent_dir)
if _parent_parent not in sys.path:
    sys.path.insert(0, _parent_parent)

try:
    _spec.loader.exec_module(_payout_utils)
finally:
    # Remove from path if we added it
    if _parent_parent in sys.path:
        sys.path.remove(_parent_parent)

# Re-export functions for backward compatibility
process_payout = _payout_utils.process_payout
complete_payout = _payout_utils.complete_payout
auto_fill_emi_from_payout = _payout_utils.auto_fill_emi_from_payout

