import os
import unittest

# the few tests that take 14-35 s each; CI and pre-merge runs set SLOW=1
SLOW = unittest.skipUnless(os.environ.get("SLOW"), "slow: set SLOW=1 to run")
