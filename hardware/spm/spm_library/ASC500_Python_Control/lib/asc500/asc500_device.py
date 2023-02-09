from .asc500_afm import ASC500AFM
from .asc500_autoapproach import ASC500AutoApproach
from .asc500_base import ASC500Base
from .asc500_coarsedevice import ASC500CoarseDevice
from .asc500_limits import ASC500Limits
from .asc500_scanner import ASC500Scanner
from .asc500_zcontrol import ASC500ZControl
from .asc500_zfeedback import ASC500ZFeedback


class Device():
    def __init__(self, binPath, dllPath, portNr=-1):
        self.afm = ASC500AFM(binPath, dllPath, portNr)
        self.aap = ASC500AutoApproach(binPath, dllPath, portNr)
        self.base = ASC500Base(binPath, dllPath, portNr)
        self.coarse = ASC500CoarseDevice(binPath, dllPath, portNr)
        self.limits = ASC500Limits(binPath, dllPath, portNr)
        self.scanner = ASC500Scanner(binPath, dllPath, portNr)
        self.zcontrol = ASC500ZControl(binPath, dllPath, portNr)
        self.zfeedback = ASC500ZFeedback(binPath, dllPath, portNr)



