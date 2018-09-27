import atexit
import copy
import logging
import os
import struct
import sys
import time
from collections import OrderedDict
from datetime import datetime
from filecmp import cmp
from zlib import crc32

from disktools.disk import Disk
from util.common import common_getattr, class2str

from util.commonYaml import fat32Yaml

FS_ENCODING = sys.getfilesystemencoding()

class FATCreator(object):
    @staticmethod
    def mkfat32FromConfig(stream, size, fat32bootSectorConfig, fsInfoConfig):
        return FATCreator.mkfat32(stream=stream, size=size, **fat32bootSectorConfig, fsInfoConfig=fsInfoConfig)

    @staticmethod
    def mkfat32(stream, size,
                  chJumpInstruction=b'\xEB\x58\x90',
                  chOemId='Test',
                  wBytesPerSector=512,
                  uchSectorsPerCluster=32,
                  wRsvdSectorsCount=32,
                  uchFatCopies=2,
                  wMaxRootEntries=0,
                  wTotalSectors=0,
                  uchMediaDescriptor=0xF8,
                  wSectorsPerFat=0,
                  wSectorsPerTrack=63,
                  wHeads=16,
                  wHiddenSectors=0,
                  dwSectorsPerFat=0,
                  dwRootCluster=2,
                  wFSISector=1,
                  wBootCopySector=6,
                  chReserved=b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
                  chPhysDriveNumber=0x80,
                  chReserved1=0x00,
                  chExtBootSignature=0x29,
                  wBootSignature=0xAA55,
                  dwVolumeID=1234567890,
                  sVolumeLabel='TEST',
                  sFSType='FAT32',
                  fsInfoConfig = None
                  ):
        '''
        Initializes boot sector parameters.

        :param size: disk size in bytes
        :type size: int
        :param chJumpInstruction: Jump instruction code
        :type chJumpInstruction: Hex-String
        :param chOemId: OEM Name
        :type chOemId: String
        :param wBytesPerSector: Bytes per sector (default: 512)
        :type wBytesPerSector: int
        :param uchSectorsPerCluster: sectors per cluster
        :type uchSectorsPerCluster: int
        :param wRsvdSectorsCount: Size in sectors of reserved area
        :type wRsvdSectorsCount: int
        :param uchFatCopies: Number of FATs. Typically two
        :type uchFatCopies: int
        :param wMaxRootEntries: Maximum number of files in root directory, for FAT12 and FAT16 only. Has to be 0 for FAT32
        :type wMaxRootEntries: int
        :param wTotalSectors: 16-bit value of number of sectors in file system
        :type wTotalSectors: int
        :param uchMediaDescriptor: Media type. Typically 0xf8 for fixed disks and 0xf0 for removable disk.
        :type uchMediaDescriptor: Hex-Value
        :param wSectorsPerFat: 16-bit size in sectors of each FAT for FAT12 and FAT16. 0 for FAT32
        :type wSectorsPerFat: int
        :param wSectorsPerTrack: Sectors per track of storage device
        :type wSectorsPerTrack: int
        :param wHeads: Number of heads in storage device
        :type wHeads: int
        :param wHiddenSectors: Number of sectors before the start of partition
        :type wHiddenSectors: int
        :param dwSectorsPerFat: 32-bit size in sectors per FAT
        :type dwSectorsPerFat: int
        :param dwRootCluster: Root directory cluster
        :type dwRootCluster: int
        :param wFSISector: Sector where FSINFO structure can be found
        :type wFSISector: int
        :param wBootCopySector: Sector where backup copy of boot sector is  located.
        :type wBootCopySector: int
        :param chReserved: Reserved
        :type chReserved: String
        :param chPhysDriveNumber: INT13h drive number
        :type chPhysDriveNumber: String
        :param chReserved1: Not used
        :type chReserved1: String
        :param chExtBootSignature: Extended boot signature to identify the next three values are valid
        :type chExtBootSignature: Char
        :param wBootSignature: boot signature
        :type wBootSignature:
        :param dwVolumeID: Volume serial number
        :type dwVolumeID: int
        :param sVolumeLabel: Volume label
        :type sVolumeLabel: String
        :param sFSType: File system type label
        :type sFSType: String
        :return: None
        :rtype: None
        '''

        sectors = size/wBytesPerSector

        # Warn if Sector counts exceeds maximum possible sector count
        if sectors > 0xFFFFFFFF:
            logging.warn("Sector count of {0} exceeds maximum allowed sector count ({1})".format(sectors, 0xFFFFFFFF))

        fsinfo = {}
        fsinfo['reserved_size'] = wRsvdSectorsCount * wBytesPerSector
        fsinfo['cluster_size'] = wBytesPerSector * uchSectorsPerCluster
        fsinfo['clusters'] = (size - fsinfo['reserved_size']) // fsinfo['cluster_size']
        fsinfo['fat_size'] = rdiv(4 * (fsinfo['clusters'] + 2), wBytesPerSector) * wBytesPerSector
        fsinfo['required_size'] = fsinfo['cluster_size'] * fsinfo['clusters'] + uchFatCopies * fsinfo['fat_size'] + fsinfo['reserved_size']

        # Check MS imposed limits
        if fsinfo['clusters'] < 65526:
            logging.warn("Too few clusters for fat32. Maximum: {0}, Current: {1}. Change parameters disk size, wBytesPerSector or uchSectorsPerCluster.".format(65526, fsinfo['clusters']))
        if fsinfo['clusters'] > 0x0FFFFFF6:
            logging.warn(
                "Too many clusters for fat32. Maximum: {0}, Current: {1}. Change parameters disk size, wBytesPerSector or uchSectorsPerCluster.".format(
                    0x0FFFFFF6, fsinfo['clusters']))
        if uchSectorsPerCluster not in (1, 2, 4, 8, 16, 32, 64, 128):
            logging.warn("Sectors per cluster " + uchSectorsPerCluster + " not valid.")

        boot = FAT32_Boot(stream=stream)
        boot.chJumpInstruction = chJumpInstruction
        #TODO: Add bootcode
        boot.chOemId = b'%-8s' % str.encode(chOemId)
        boot.wBytesPerSector = wBytesPerSector
        boot.uchSectorsPerCluster = uchSectorsPerCluster
        boot.uchSectorsPerCluster = uchSectorsPerCluster
        boot.wSectorsCount = wRsvdSectorsCount
        boot.uchFATCopies = uchFatCopies
        boot.wMaxRootEntries = wMaxRootEntries
        boot.wTotalSectors = wTotalSectors
        boot.uchMediaDescriptor = uchMediaDescriptor
        boot.wSectorsPerFAT = wSectorsPerFat
        boot.wSectorsPerTrack = wSectorsPerTrack
        boot.wHeads = wHeads
        boot.wHiddenSectors = wHiddenSectors
        boot.dwTotalLogicalSectors = int(sectors)
        if dwSectorsPerFat != 0:
            boot.dwSectorsPerFAT = dwSectorsPerFat
        else:
            boot.dwSectorsPerFAT = int(fsinfo['fat_size']/wBytesPerSector)
        # TODO: wMirroringFlags
        boot.wMirroringFlags = 0
        # TODO: wVersion
        boot.wVersion = 0

        boot.dwRootCluster = dwRootCluster
        boot.wFSISector = wFSISector
        boot.wBootCopySector = wBootCopySector
        boot.chReserved = chReserved

        boot.chPhysDriveNumber = chPhysDriveNumber
        boot.chReserved1 = chReserved1

        boot.chExtBootSignature = chExtBootSignature
        boot.wBootSignature = wBootSignature
        boot.dwVolumeID = dwVolumeID
        boot.sVolumeLabel = b'%-11s' % str.encode(sVolumeLabel)
        boot.sFSType = b'%-8s' % str.encode(sFSType)

        fsi = FAT32FSINFO(offset=wBytesPerSector)
        fsi.initFSInfo()
        if fsInfoConfig:
            fsi.initFsInfoFromConfig(fsInfoConfig)

        if fsi.dwFreeClusters == 0 and fsInfoConfig is None:
            logging.debug("Automatic correction of free cluster field in FSINO (Count: {0})".format(fsinfo['clusters'] - 1))
            fsi.dwFreeClusters = int(fsinfo['clusters'] - 1)

        stream.seek(0)

        stream.write(boot.pack())
        stream.write(fsi.pack())
        if boot.wBootCopySector:
            stream.seek(boot.wBootCopySector * boot.wBytesPerSector)
            stream.write(boot.pack())
            stream.write(fsi.pack())

        # Create blank FAT areas

        stream.seek(boot.fat())
        blank = bytearray(boot.wBytesPerSector)
        for i in range(boot.dwSectorsPerFAT * 2):
            stream.write(blank)

        # Initialize FAT1
        clus_0_2 = b'\xF8\xFF\xFF\x0F\xFF\xFF\xFF\xFF\xF8\xFF\xFF\x0F'
        stream.seek(boot.wSectorsCount * boot.wBytesPerSector)
        stream.write(clus_0_2)

        # ... and FAT2
        if boot.uchFATCopies == 2:
            stream.seek(boot.fat(1))
            stream.write(bytearray(boot.cluster))

        # Blank root directory
        stream.seek(boot.root())
        stream.write(bytearray(boot.cluster))

        sizes = {0: 'B', 10: 'KiB', 20: 'MiB', 30: 'GiB', 40: 'TiB', 50: 'EiB'}
        k = 0
        for k in sorted(sizes):
            if (fsinfo['required_size'] / (1 << k)) < 1024: break

        free_clusters = fsinfo['clusters'] - 1
        print("Successfully applied FAT32 to a %.02f %s volume.\n%d clusters of %.1f KB.\n%.02f %s free in %d clusters." % (
            fsinfo['required_size'] / float(1 << k), sizes[k], fsinfo['clusters'], fsinfo['cluster_size'] / 1024.0,
            free_clusters * boot.cluster / float(1 << k), sizes[k], free_clusters))
        print("\nFAT #1 @0x%X, Data Region @0x%X, Root (cluster #%d) @0x%X" % (
            boot.fatoffs, boot.cl2offset(2), 2, boot.cl2offset(2)))
        return boot, fsi

class FAT32(object):
    '''
    Parent class for all FAT32 operations.

    :param stream: Disk stream for writing and reading
    :type stream: Disk
    '''
    def __init__(self, s=None, stream = None):
        self.stream = stream
        self.boot = FAT32_Boot(s=s, stream=stream)
        self.fsinfo = FAT32FSINFO(s=stream.read(512), stream=stream, offset=self.boot.wBytesPerSector)


    def writeNew(self):
        '''
        Initializes new FAT filesystem in disk, including new FAT boot sector, FSInfo parameters and FATs and backup copies. Blanking root directory

        :return: 0 for success, 1 for error
        :rtype: int
        '''
        if not self.stream:
            raise Exception("No stream given for writing!")
        else:
            self.stream.seek(0)

            self.stream.write(self.boot.pack())
            self.stream.write(self.fsinfo.pack())
            if self.boot.wBootCopySector:
                self.stream.seek(self.boot.wBootCopySector * self.boot.wBytesPerSector)
                self.stream.write(self.boot.pack())
                self.stream.write(self.fsinfo.pack())

        # Create blank FAT areas
        self.stream.seek(self.boot.fat())
        blank = bytearray(self.boot.wBytesPerSector)
        for i in range(self.boot.dwSectorsPerFAT * 2):
            self.stream.write(blank)

        # Initialize FAT1
        clus_0_2 = b'\xF8\xFF\xFF\x0F\xFF\xFF\xFF\xFF\xF8\xFF\xFF\x0F'
        self.stream.seek(self.boot.wSectorsCount * self.boot.wBytesPerSector)
        self.stream.write(clus_0_2)

        # ... and FAT2
        if self.boot.uchFATCopies == 2:
            self.stream.seek(self.boot.fat(1))
            self.stream.write(bytearray(self.boot.cluster))

        # Blank root directory
        self.stream.seek(self.boot.root())
        self.stream.write(bytearray(self.boot.cluster))

        # sizes = {0:'B', 10:'KiB',20:'MiB',30:'GiB',40:'TiB',50:'EiB'}
        # k = 0
        # requiredsize = self.boot.fatsize * self.boot.uchSectorsPerCluster*self.boot.wBytesPerSector
        # for k in sorted(sizes):
        #     if (requiredsize / (1<<k)) < 1024: break
        #
        # free_clusters = self.boot.fsinfo['clusters'] - 1
        # print("Successfully applied FAT32 to a %.02f %s volume.\n%d clusters of %.1f KB.\n%.02f %s free in %d clusters." % (requiredsize/float(1<<k), sizes[k], self.boot.fsinfo['clusters'], self.boot.fsinfo['cluster_size']/1024.0, free_clusters*self.boot.cluster/float(1<<k), sizes[k], free_clusters))
        # print("\nFAT #1 @0x%X, Data Region @0x%X, Root (cluster #%d) @0x%X" % (self.boot.fatoffs, self.boot.cl2offset(2), 2, self.boot.cl2offset(2)))

        return 0



class FAT32_Boot(object):
    '''
    FAT32 Boot sector

    :param offset: Offset on disk
    :type offset: int
    '''
    layout = {
        0x00: ('chJumpInstruction', '3s'),
        0x03: ('chOemId', '8s'),
        0x0B: ('wBytesPerSector', '<H'),
        0x0D: ('uchSectorsPerCluster', 'B'),
        0x0E: ('wSectorsCount', '<H'),  # reserved sectors (min 32?)
        0x10: ('uchFATCopies', 'B'),
        0x11: ('wMaxRootEntries', '<H'),
        0x13: ('wTotalSectors', '<H'),
        0x15: ('uchMediaDescriptor', 'B'),
        0x16: ('wSectorsPerFAT', '<H'),  # not used, see 24h instead
        0x18: ('wSectorsPerTrack', '<H'),
        0x1A: ('wHeads', '<H'),
        0x1C: ('wHiddenSectors', '<H'),
        # 0x1E: ('wTotalHiddenSectors', '<H'),
        0x20: ('dwTotalLogicalSectors', '<I'),
        0x24: ('dwSectorsPerFAT', '<I'),
        0x28: ('wMirroringFlags', '<H'),  # bits 0-3: active FAT, it bit 7 set; else: mirroring as usual
        0x2A: ('wVersion', '<H'),
        0x2C: ('dwRootCluster', '<I'),  # usually 2
        0x30: ('wFSISector', '<H'),  # usually 1
        0x32: ('wBootCopySector', '<H'),  # 0x0000 or 0xFFFF if unused, usually 6
        0x34: ('chReserved', '12s'),
        0x40: ('chPhysDriveNumber', 'B'),
        0x41: ('chReserved1', 'B'),
        0x42: ('chExtBootSignature', 'B'),
        0x43: ('dwVolumeID', '<I'),
        0x47: ('sVolumeLabel', '11s'),
        0x52: ('sFSType', '8s'),
        # ~ 0x72: ('chBootstrapCode', '390s'),
        0x1FE: ('wBootSignature', '<H')  # 55 AA
    }

    def __init__(self, s=None, offset = 0, stream=None):
        logging.debug("Init FAT32 Bootcode")
        self._i = 0
        self._pos = offset  # base offset of bootsector
        self._buf = s or bytearray(512)
        self.stream = stream
        self._kv = self.layout.copy()
        self._vk = {}  # { name: offset}
        for k, v in self._kv.items():
            self._vk[v[0]] = k
            getattr(self, v[0])
        self.__init2__()



    def __init2__(self):
        '''
        Method for updating FSInfo and calculating some offset parameter

        :return: None
        :rtype: None
        '''
        if not self.wBytesPerSector: return

        # Cluster size in bytes
        self.cluster = self.wBytesPerSector * self.uchSectorsPerCluster

        # Offset of first FAT copy
        self.fatoffs = self.wSectorsCount * self.wBytesPerSector + self._pos

        # Data area offset
        self.dataoffs = self.fatoffs + self.uchFATCopies * self.dwSectorsPerFAT * self.wBytesPerSector + self._pos

        # Number of cluster represented in this FAT
        self.fatsize = self.dwTotalLogicalSectors/self.uchSectorsPerCluster

        if self.stream:
            self.fsinfo = FAT32FSINFO(stream=self.stream, offset=self.wFSISector * self.wBytesPerSector)
        else:
            self.fsinfo = None

    __getattr__ = common_getattr

    def __str__ (self):
        return class2str(self, "FAT32 Boot Sector @%x\n" % self._pos)

    def mkfatFromConfig(self, size, fat32BootConfig, fsinfoConfig):
        '''
        Initializes boot sector parameters from config.

        :param size: disk size in bytes
        :type size: int
        :param fat32BootConfig: FAT32 boot sector parameter
        :type fat32BootConfig: FAT32BootParameter
        :return:
        :rtype:
        '''
        self.mkfat(size, fsinfoConfig = fsinfoConfig, **fat32BootConfig)

    def mkfat(self, size,
              chJumpInstruction = b'\xEB\x58\x90',
              chOemId = 'Test',
              wBytesPerSector = 512,
              uchSectorsPerCluster = 32,
              wRsvdSectorsCount = 32,
              uchFatCopies = 2,
              wMaxRootEntries=0,
              wTotalSectors=0,
              uchMediaDescriptor=0xF8,
              wSectorsPerFat=0,
              wSectorsPerTrack=63,
              wHeads=16,
              wHiddenSectors=0,
              dwSectorsPerFat = 0,
              dwRootCluster = 2,
              wFSISector = 1,
              wBootCopySector = 6,
              chReserved = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
              chPhysDriveNumber = 0x80,
              chReserved1 = 0x00,
              chExtBootSignature = 0x29,
              wBootSignature = 0xAA55,
              dwVolumeID = 1234567890,
              sVolumeLabel = 'TEST',
              sFSType = 'FAT32',
              fsInfoConfig = None
              ):
        '''
        Initializes boot sector parameters.

        :param size: disk size in bytes
        :type size: int
        :param chJumpInstruction: Jump instruction code
        :type chJumpInstruction: Hex-String
        :param chOemId: OEM Name
        :type chOemId: String
        :param wBytesPerSector: Bytes per sector (default: 512)
        :type wBytesPerSector: int
        :param uchSectorsPerCluster: sectors per cluster
        :type uchSectorsPerCluster: int
        :param wRsvdSectorsCount: Size in sectors of reserved area
        :type wRsvdSectorsCount: int
        :param uchFatCopies: Number of FATs. Typically two
        :type uchFatCopies: int
        :param wMaxRootEntries: Maximum number of files in root directory, for FAT12 and FAT16 only. Has to be 0 for FAT32
        :type wMaxRootEntries: int
        :param wTotalSectors: 16-bit value of number of sectors in file system
        :type wTotalSectors: int
        :param uchMediaDescriptor: Media type. Typically 0xf8 for fixed disks and 0xf0 for removable disk.
        :type uchMediaDescriptor: Hex-Value
        :param wSectorsPerFat: 16-bit size in sectors of each FAT for FAT12 and FAT16. 0 for FAT32
        :type wSectorsPerFat: int
        :param wSectorsPerTrack: Sectors per track of storage device
        :type wSectorsPerTrack: int
        :param wHeads: Number of heads in storage device
        :type wHeads: int
        :param wHiddenSectors: Number of sectors before the start of partition
        :type wHiddenSectors: int
        :param dwSectorsPerFat: 32-bit size in sectors per FAT
        :type dwSectorsPerFat: int
        :param dwRootCluster: Root directory cluster
        :type dwRootCluster: int
        :param wFSISector: Sector where FSINFO structure can be found
        :type wFSISector: int
        :param wBootCopySector: Sector where backup copy of boot sector is  located.
        :type wBootCopySector: int
        :param chReserved: Reserved
        :type chReserved: String
        :param chPhysDriveNumber: INT13h drive number
        :type chPhysDriveNumber: String
        :param chReserved1: Not used
        :type chReserved1: String
        :param chExtBootSignature: Extended boot signature to identify the next three values are valid
        :type chExtBootSignature: Char
        :param wBootSignature: boot signature
        :type wBootSignature:
        :param dwVolumeID: Volume serial number
        :type dwVolumeID: int
        :param sVolumeLabel: Volume label
        :type sVolumeLabel: String
        :param sFSType: File system type label
        :type sFSType: String
        :return: None
        :rtype: None
        '''
        sectors = int(size / wBytesPerSector)

        if (sectors > 0xFFFFFF):
            logging.critical("Too many sectors for FAT32 file system. Please lower size or higher sector size.")
            raise Exception("Too many sectors for FAT32 file system. Please lower size or higher sector size.")

        self.chJumpInstruction = chJumpInstruction
        self.chOemId = b'%-8s' % str.encode(chOemId)
        self.wBytesPerSector = wBytesPerSector

        # Check valid uchSectorsPerCluster
        # TODO: BytesPerCluster not greater than 32k (32 * 1024)
        if uchSectorsPerCluster not in (1, 2, 4, 8, 16, 32, 64, 128):
            logging.warn("Sectors per cluster " + uchSectorsPerCluster + " not valid.")
            # self.uchSectorsPerCluster = 32

        self.uchSectorsPerCluster = uchSectorsPerCluster

        self.uchSectorsPerCluster = uchSectorsPerCluster
        self.wSectorsCount = wRsvdSectorsCount
        self.uchFATCopies = uchFatCopies
        self.wMaxRootEntries = wMaxRootEntries
        self.wTotalSectors = wTotalSectors

        # TODO: validate Media descriptor
        self.uchMediaDescriptor = uchMediaDescriptor
        self.wSectorsPerFAT = wSectorsPerFat
        self.wSectorsPerTrack = wSectorsPerTrack
        self.wHeads = wHeads
        self.wHiddenSectors = wHiddenSectors
        self.dwTotalLogicalSectors = sectors

        reserved_size = wRsvdSectorsCount * wBytesPerSector
        allowed = {}  # {cluster_size : fsinfo}

        for i in range(9, 17):  # cluster sizes 0.5K...64K
            self.fsinfo = {}
            cluster_size = (2 ** i)
            clusters = (size - reserved_size) / cluster_size
            fat_size = rdiv(4 * (clusters + 2), wBytesPerSector) * wBytesPerSector
            required_size = cluster_size * clusters + uchFatCopies * fat_size + reserved_size
            while required_size > size:
                clusters -= 1
                fat_size = rdiv(4 * (clusters + 2), wBytesPerSector) * wBytesPerSector
                required_size = cluster_size * clusters + uchFatCopies * fat_size + reserved_size
            if (clusters < 65526 ) or clusters > 0x0FFFFFF6:  # MS imposed limits
                continue
            self.fsinfo['required_size'] = int(required_size)  # space occupied by FS
            self.fsinfo['reserved_size'] = reserved_size  # space reserved before FAT#1
            self.fsinfo['cluster_size'] = cluster_size
            self.fsinfo['clusters'] = int(clusters)
            self.fsinfo['fat_size'] = int(fat_size)  # space occupied by a FAT copy
            allowed[cluster_size] = self.fsinfo

        # TODO: Which sector per Fat to choose?
        self.fsinfo = allowed[wBytesPerSector * uchSectorsPerCluster]
        self._clusters = self.fsinfo['clusters']
        # calculated, if parameter is not 0 than value ist set without validation
        if dwSectorsPerFat != 0:
            self.dwSectorsPerFAT = dwSectorsPerFat
        else:
            self.dwSectorsPerFAT = int(self.fsinfo['fat_size']/wBytesPerSector)

        # TODO: wMirroringFlags
        self.wMirroringFlags = 0
        # TODO: wVersion
        self.wVersion = 0

        self.dwRootCluster = dwRootCluster
        self.wFSISector = wFSISector
        self.wBootCopySector = wBootCopySector

        # TODO: chReserved filling
        #self.chReserved = b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
        self.chReserved = chReserved

        self.chPhysDriveNumber = chPhysDriveNumber

        # TODO: chFlags
        self.chReserved1 = chReserved1

        self.chExtBootSignature = chExtBootSignature
        self.wBootSignature = wBootSignature
        self.dwVolumeID = dwVolumeID
        self.sVolumeLabel = b'%-11s' % str.encode(sVolumeLabel)
        self.sFSType = b'%-8s' % b'FAT32'



        #self.__init2__()

    def pack(self):
        '''
        Packs attributes to struct. Mapping of sizes is done with layout dictionary.

        :return: Buffer object with mapped attributes
        :rtype: Bytearray
        '''

        for k, v in self._kv.items():
            logging.debug("Packing Fat boot sector parameters: " + v[0])
            self._buf[k:k+struct.calcsize(v[1])] = struct.pack(v[1], getattr(self, v[0]))
            logging.debug("Value of parameter: " + str(self._buf[k:k+struct.calcsize(v[1])]))
        # TODO: init2 in fat
        self.__init2__()
        return self._buf

    def fat(self, fatcopy=0):
        '''
        Returns position of given fatcopy in bytes

        :param fatcopy: Number of fatcopy (0: default, 1: first copy)
        :return: Position of FAT in bytes
        '''
        return self.fatoffs + fatcopy * self.dwSectorsPerFAT * self.wBytesPerSector

    def root(self):
        '''
        Returns the real offset of the root directory

        :return: Offset of root directory
        '''
        return self.cl2offset(self.dwRootCluster)

    def cl2offset(self, cluster):
        '''
        Returns the real offset of a cluster from disk start

        :param cluster: Number of cluster
        :return: Offset of cluster
        '''
        return self.dataoffs + (cluster - 2) * self.cluster

    def clusters(self):
        '''
        Return the number of clusters in the data area

        :return: Number of clusters in data area
        :rtype: int
        '''
        return (self.dwTotalLogicalSectors - (self.dataoffs//self.wBytesPerSector)) // self.uchSectorsPerCluster




class FAT32FSINFO(object):
    layout = {  # { offset: (name, unpack string) }
        0x00: ('sSignature1', '4s'),  # RRaA
        0x04: ('sReserved1', '480s'),
        0x1E4: ('sSignature2', '4s'),  # rrAa
        0x1E8: ('dwFreeClusters', '<I'),  # 0xFFFFFFFF if unused (may be incorrect)
        0x1EC: ('dwNextFreeCluster', '<I'),  # hint only (0xFFFFFFFF if unused)
        0x1F0: ('sReserved2', '12s'),
        0x1FE: ('wBootSignature', '<H')  # 55 AA
    }  # Size = 0x200 (512 byte)

    def __init__(self, s = None, offset = 0, stream: Disk = None):
        logging.debug("Init FAT32 FSINFO")
        self._i = 0
        self._pos = offset
        self._buf = s or bytearray(512)
        self.stream = stream
        self._kv = self.layout.copy()
        self._vk = {}  # { name: offset}
        for k, v in self._kv.items():
            self._vk[v[0]] = k
            getattr(self, v[0])

    __getattr__ = common_getattr

    def __str__ (self):
        return class2str(self, "FAT32 FSInfo Sector @%x\n" % self._pos)

    def pack(self):
        "Update internal buffer"
        for k, v in self._kv.items():
            logging.debug("Packing Fat boot sector parameters: " + v[0])
            self._buf[k:k+struct.calcsize(v[1])] = struct.pack(v[1], getattr(self, v[0]))
        return self._buf

    def initFsInfoFromConfig(self, fsInfoConfig):
        self.initFSInfo(**fsInfoConfig)

    def initFSInfo(self, sSignature1 ='RRaA', sReserved1 = '', sSignature2 ='rrAa', dwFreeClusters = 0, dwNextFreeCluster = 3, sReserved2 = '', wBootSignature = 0xAA55):
        self.sSignature1 = str.encode(sSignature1)
        self.sSignature2 = str.encode(sSignature2)

        # Transform sReserved1 to Bytearray, length 480
        reserved1 = bytearray(480)
        reserved1[0:0] = str.encode(sReserved1)
        self.sReserved1 = reserved1
        self.dwFreeClusters = dwFreeClusters
        self.dwNextFreeCluster = dwNextFreeCluster
        reserved2 = bytearray(12)
        reserved2[0:0] = str.encode(sReserved2)
        self.sReserved2 = reserved2
        self.wBootSignature = wBootSignature

class FAT(object):
    def __init__(self, stream, offset, clusters, bitsize=32):
        self.stream = stream
        self.size = clusters
        self.bits = bitsize
        self.offset = offset
        self.offset2 = offset + rdiv(rdiv(clusters*bitsize, 8), 512) * 512
        self.reserved = 0x0FFFFFF7
        self.bad = 0x0FFFFFF7
        self.last = 0x0FFFFFF8
        self.fat_slot_size = 4
        self.fat_slot_fmt = '<I'

        # maximum cluster index addressable
        self.real_last = min(self.reserved-1, self.size+2-1)
        self.decoded = {} # {cluster index: cluster content}
        self.last_free_alloc = 2 # last free cluster allocated (see in FSInfo)
        self.free_clusters = None # tracks free cluster

        # ordered by offset, dictionary {first cluster: run_length}
        self.free_clusters_map = None
        self.map_free_space()
        self.free_clusters_flag = 1

    def __getitem__ (self, index):
        "Retrieve the value stored in a given cluster index"
        try:
            assert 2 <= index <= self.real_last
        except AssertionError:
            logging.debug("Attempt to read unexistant FAT index #%d", index)
            raise Exception("Attempt to read unexistant FAT index #%d" % index)
            return self.last
        slot = self.decoded.get(index)
        if slot: return slot
        pos = self.offset+(index*self.bits)//8
        self.stream.seek(pos)
        slot = struct.unpack(self.fat_slot_fmt, self.stream.read(self.fat_slot_size))[0]
        #~ print "getitem", self.decoded
        if self.bits == 12:
            # Pick the 12 bits we want
            if index % 2: # odd cluster
                slot = slot >> 4
            else:
                slot = slot & 0x0FFF
        self.decoded[index] = slot
        logging.debug("Got FAT1[0x%X]=0x%X @0x%X", index, slot, pos)
        return slot

        # Defer write on FAT#2 allowing undelete?

    def __setitem__(self, index, value):
        "Set the value stored in a given cluster index"
        try:
            assert 2 <= index <= self.real_last
        except AssertionError:
            logging.debug("Attempt to set invalid cluster index 0x%X with value 0x%X", index, value)
            return
        try:
            assert value <= self.real_last or value >= self.reserved
        except AssertionError:
            logging.debug("Attempt to set invalid value 0x%X in cluster 0x%X", value, index)
            return
        self.decoded[index] = value
        dsp = (index * self.bits) // 8
        pos = self.offset + dsp
        if self.bits == 12:
            # Pick and set only the 12 bits we want
            self.stream.seek(pos)
            slot = struct.unpack(self.fat_slot_fmt, self.stream.read(self.fat_slot_size))[0]
            if index % 2:  # odd cluster
                # Value's 12 bits moved to top ORed with original bottom 4 bits
                # ~ print "odd", hex(value), hex(slot), self.decoded
                value = (value << 4) | (slot & 0xF)
                # ~ print hex(value), hex(slot)
            else:
                # Original top 4 bits ORed with value's 12 bits
                # ~ print "even", hex(value), hex(slot)
                value = (slot & 0xF000) | value
                # ~ print hex(value), hex(slot)
        logging.debug("setting FAT1[0x%X]=0x%X @0x%X", index, value, pos)
        self.stream.seek(pos)
        value = struct.pack(self.fat_slot_fmt, value)
        self.stream.write(value)
        pos = self.offset2 + dsp
        # ~ log("setting FAT2[%Xh]=%Xh @%Xh", index, value, pos)
        self.stream.seek(pos)
        self.stream.write(value)

    def map_free_space(self):
        "Maps the free clusters in an ordered dictionary {start_cluster: run_length}"
        startpos = self.stream.tell()
        self.free_clusters_map = {}
        FREE_CLUSTERS=0
        if self.bits < 32:
            # FAT16 is max 130K...
            PAGE = int(self.offset2 - self.offset - (2*self.bits)/8)
        else:
            # FAT32 could reach ~1GB!
            PAGE = 1<<20
        END_OF_CLUSTERS = int(self.offset + rdiv(self.size*self.bits, 8) + (2*self.bits)/8)
        i = self.offset+(2*self.bits)//8 # address of cluster #2
        self.stream.seek(i)
        while i < END_OF_CLUSTERS:
            s = self.stream.read(min(PAGE, END_OF_CLUSTERS-i)) # slurp full FAT, or 1M page if FAT32
            logging.debug("map_free_space: loaded FAT page of %d bytes @0x%X", len(s), i)
            j=0
            while j < len(s):
                first_free = -1
                run_length = -1
                while j < len(s):
                    if self.bits == 32:
                        if s[j] != 0 or s[j+1] != 0 or s[j+2] != 0 or s[j+3] != 0:
                            j += 4
                            if run_length > 0: break
                            continue
                    elif self.bits == 16:
                        if s[j] != 0 or s[j+1] != 0:
                            j += 2
                            if run_length > 0: break
                            continue
                    elif self.bits == 12:
                        # Pick the 12 bits wanted
                        #     0        1        2
                        # AAAAAAAA AAAABBBB BBBBBBBB
                        if not j%3:
                            if s[j] != 0 or s[j+1]>>4 != 0:
                                j += 1
                                if run_length > 0: break
                                continue
                        elif j%3 == 1:
                            j+=1
                            continue # simply skips median byte
                        else: # j%3==2
                            if s[j] != 0 or s[j-1] & 0x0FFF != 0:
                                j += 1
                                if run_length > 0: break
                                continue
                    if first_free < 0:
                        first_free = (i-self.offset+j)*8//self.bits
                        logging.debug("map_free_space: found run from %d", first_free)
                        run_length = 0
                    run_length += 1
                    j+=self.bits//8
                if first_free < 0: continue
                FREE_CLUSTERS+=run_length
                self.free_clusters_map[first_free] =  run_length
                logging.debug("map_free_space: appended run (%d, %d)", first_free, run_length)
            i += len(s) # advance to next FAT page to examine
        self.stream.seek(startpos)
        self.free_clusters = FREE_CLUSTERS
        logging.debug("map_free_space: %d clusters free in %d runs", FREE_CLUSTERS, len(self.free_clusters_map))
        return FREE_CLUSTERS, len(self.free_clusters_map)

    def count(self, startcluster):
        "Count the clusters in a chain. Returns a tuple (<total clusters>, <last cluster>)"
        n = 1
        while not (self.last <= self[startcluster] <= self.last+7): # islast
            startcluster = self[startcluster]
            n += 1
        return (n, startcluster)

    def count_run(self, start, count=0):
        """Returns the count of the clusters in a contiguous run from 'start'
        and the next cluster (or END CLUSTER mark), eventually limiting to the first 'count' clusters"""
        #~ print "count_run(%Xh, %d)" % (start, count)
        n = 1
        while 1:
            if self.last <= start <= self.last+7: # if end cluster
                break
            prev = start
            start = self[start]
            # If next LCN is not contig
            if prev != start-1:
                break
            # If max run length reached
            if count > 0:
                if  count-1 == 0:
                    break
                else:
                    count -= 1
            n += 1
        return n, start

    def alloc(self, runs_map, count, params={}):
        """Allocates a set of free clusters, marking the FAT.
        runs_map is the dictionary of previously allocated runs
        count is the number of clusters to allocate
        params is an optional dictionary of directives to tune the allocation (to be done).
        Returns the last cluster or raise an exception in case of failure"""
        self.map_compact()

        if self.free_clusters < count:
            logging.debug("Couldn't allocate %d cluster(s), only %d free", count, self.free_clusters)
            raise Exception(
                "FATAL! Free clusters exhausted, couldn't allocate %d, only %d left!" % (count, self.free_clusters))

            logging.debug("Ok to allocate %d cluster(s), %d free", count, self.free_clusters)

        last_run = None

        while count:
            if runs_map:
                last_run = runs_map.items()[-1]
            i, n = self.findfree(count)
            self.mark_run(i, n)  # marks the FAT
            if last_run:
                self[last_run[0] + last_run[1] - 1] = i  # link prev chain with last
            if last_run and i == last_run[0] + last_run[1]:  # if contiguous
                runs_map[last_run[0]] = n + last_run[1]
            else:
                runs_map[i] = n
            last = i + n - 1  # last cluster in new run
            count -= n

        self[last] = self.last
        self.last_free_alloc = last

        logging.debug("New runs map: %s", runs_map)
        return last

    def map_compact(self, strategy=0):
        "Compacts, eventually reordering, the free space runs map"
        if not self.free_clusters_flag: return
        #~ print "Map before:", sorted(self.free_clusters_map.iteritems())
        map_changed = 0
        while 1:
            d=copy.copy(self.free_clusters_map)
            for k,v in sorted(self.free_clusters_map.items()):
                while d.get(k+v): # while contig runs exist, merge
                    v1 = d.get(k+v)
                    logging.debug("Compacting free_clusters_map: {%d:%d} -> {%d:%d}", k,v,k,v+v1)
                    d[k] = v+v1
                    del d[k+v]
                    #~ print "Compacted {%d:%d} -> {%d:%d}" %(k,v,k,v+v1)
                    #~ print sorted(d.iteritems())
                    v+=v1
            if self.free_clusters_map != d:
                self.free_clusters_map = d
                map_changed = 1
                continue
            break
        self.free_clusters_flag = 0
        #~ if strategy == 1:
            #~ self.free_clusters_map = OrderedDict(sorted(self.free_clusters_map.items(), key=lambda t: t[0])) # sort by disk offset
        #~ elif strategy == 2:
            #~ self.free_clusters_map = OrderedDict(sorted(self.free_clusters_map.items(), key=lambda t: t[1])) # sort by run size
        logging.debug("Free space map - %d run(s): %s", len(self.free_clusters_map), self.free_clusters_map)
        #~ print "Map AFTER:", sorted(self.free_clusters_map.iteritems())

    def findfree(self, count=0):
        """Return index and length of the first free clusters run beginning from
        'start' or (-1,0) in case of failure. If 'count' is given, limit the search
        to that amount."""
        if self.free_clusters_map == None:
            self.map_free_space()
        try:
            i, n = self.free_clusters_map.popitem()
        except KeyError:
            return -1, -1
        logging.debug("got run of %d free clusters from #%x", n, i)
        if n - count > 0:
            self.free_clusters_map[i + count] = n - count  # updates map
        self.free_clusters -= min(n, count)
        return i, min(n, count)

    def mark_run(self, start, count, clear=False):
        "Mark a range of consecutive FAT clusters (optimized for FAT16/32)"
        if not count: return
        logging.debug("mark_run(%Xh, %d, clear=%d)", start, count, clear)
        if self.bits == 12:
            while count:
                self[start] = (start+1, 0)(clear==True)
                start+=1
                count-=1
            self.free_clusters_flag = 1
            self.free_clusters_map[start] = count
            return
        dsp = (start*self.bits)/8
        pos = self.offset+dsp
        self.stream.seek(pos)
        if clear:
            for i in range(start, start+count):
                self.decoded[i] = 0
            self.stream.write(bytearray(count*(self.bits//8)*b'\x00'))
            self.free_clusters_flag = 1
            self.free_clusters_map[start] = count
            return
        # consecutive values to set
        L = range(start+1, start+1+count)
        for i in L:
            self.decoded[i-1] = i
        self.decoded[start+count-1] = self.last
        # converted in final LE WORD/DWORD array
        L = map(lambda x: struct.pack(self.fat_slot_fmt, x), L)

        #L[-1] = struct.pack(self.fat_slot_fmt, self.last)
        self.stream.write(bytearray().join(L))

    def free(self, start, runs=None):
        "Free a clusters chain, one run at a time (except FAT12)"
        self.free_clusters_flag = 1
        if runs:
            for run in runs:
                logging.debug("free: directly zeroing run of %d clusters from %Xh", runs[run], run)
                self.mark_run(run, runs[run], True)
                self.free_clusters += runs[run]
                self.free_clusters_map[run] = runs[run]
            return

        while True:
            length, next = self.count_run(start)
            logging.debug("free: count_run returned %d, %Xh", length, next)
            logging.debug("free: zeroing run of %d clusters from %Xh (next=%Xh)", length, start, next)
            self.mark_run(start, length, True)
            self.free_clusters += length
            self.free_clusters_map[start] = length
            start = next
            if next == self.last: break


class Chain(object):
    "Opens a cluster chain or run like a plain file"
    def __init__ (self, boot, fat, cluster, size=0, nofat=0, end=0):
        self.isdirectory=False
        self.stream = boot.stream
        self.boot = boot
        self.fat = fat
        self.start = cluster # start cluster or zero if empty
        self.end = end # end cluster
        self.nofat = nofat # 0=uses FAT (fragmented)
        self.size = rdiv(size, boot.cluster)*boot.cluster
        # Size in bytes of allocated cluster(s)
        if self.start and (not nofat or not self.fat.exfat):
            if not size or not end:
                self.size, self.end = fat.count(cluster)
                self.size *= boot.cluster
        else:
            self.size = rdiv(size, boot.cluster)*boot.cluster
            self.end = cluster+ rdiv(size, boot.cluster)
        self.filesize = size or self.size # file size, if available, or chain size
        self.pos = 0 # virtual stream linear pos
        # Virtual Cluster Number (cluster index in this chain)
        self.vcn = 0
        # Virtual Cluster Offset (current offset in VCN)
        self.vco = 0
        self.lastvlcn = (0, cluster) # last cluster VCN & LCN
        self.runs = OrderedDict() # RLE map of fragments
        if self.start:
            self._get_frags()
        logging.debug("Cluster chain of %d%sbytes (%d bytes) @LCN %Xh:LBA %Xh", self.filesize, (' ', ' contiguous ')[nofat], self.size, cluster, self.boot.cl2offset(cluster))

    def __str__ (self):
        return "Chain of %d (%d) bytes from LCN %Xh (LBA %Xh)" % (self.filesize, self.size, self.start, self.boot.cl2offset(self.start))

    def _get_frags(self):
        "Maps the cluster runs composing the chain"
        start = self.start
        if self.nofat:
            self.runs[start] = self.size/self.boot.cluster
        else:
            while 1:
                length, next = self.fat.count_run(start)
                self.runs[start] = length
                if next == self.fat.last or next==start+length-1: break
                start = next
                logging.debug("Runs map for %s: %s", self, self.runs)

    def _alloc(self, count):
        "Allocates some clusters and updates the runs map. Returns last allocated LCN"
        self.end = self.fat.alloc(self.runs, count)
        if not self.start:
            self.start = list(self.runs.keys())[0]
        self.nofat = (len(self.runs)==1)
        self.size += count * self.boot.cluster
        return self.end

    def maxrun4len(self, length):
        "Returns the longest run of clusters, up to 'length' bytes, from current position"
        if not self.runs:
            self._get_frags()
        n = rdiv(length, self.boot.cluster) # contig clusters searched for
        found = 0
        items = self.runs.items()
        for start, count in items:
            # if current LCN is in run
            if start <= self.lastvlcn[1] < start+count:
                found=1
                break
        if not found:
            logging.fatal("FATAL! maxrun4len did NOT found current LCN!", self.runs, self.lastvlcn)
            assert 0
        left = start+count-self.lastvlcn[1] # clusters to end of run
        run = min(n, left)
        maxchunk = run*self.boot.cluster
        if n < left:
            next = self.lastvlcn[1]+n
        else:
            i = list(items).index((start, count))
            if i == len(items)-1:
                next = self.fat.last
            else:
                next = items[i+1][0] # first of next run
        # Updates VCN & next LCN
        self.lastvlcn = (self.lastvlcn[0]+n, next)
        logging.debug("Chain%08X: maxrun4len(%d) on %s, maxchunk of %d bytes, lastvlcn=%s", self.start, length, self.runs, maxchunk, self.lastvlcn)
        return maxchunk

    def tell(self): return self.pos

    def realtell(self):
        return self.boot.cl2offset(self.lastvlcn[1])+self.vco

    def seek(self, offset, whence=0):
        if whence == 1:
            self.pos += offset
        elif whence == 2:
            if self.size:
                self.pos = self.size - offset
        else:
            self.pos = offset
        # allocate some clusters if needed (in write mode)
        if self.pos > self.size:
            if self.boot.stream.mode == 'r+b':
                clusters = rdiv(self.pos, self.boot.cluster) - self.size//self.boot.cluster
                self._alloc(clusters)
                logging.debug("Chain%08X: allocated %d cluster(s) seeking %Xh", self.start, clusters, self.pos)
            else:
                self.pos = self.size
        # Maps Virtual Cluster Number (chain cluster) to Logical Cluster Number (disk cluster)
        self.vcn = self.pos // self.boot.cluster # n-th cluster chain
        self.vco = self.pos % self.boot.cluster # offset in it

        vcn = 0
        for start, count in self.runs.items():
            # if current VCN is in run
            if vcn <= self.vcn < vcn+count:
                lcn = start + self.vcn - vcn
                #~ print "Chain%08X: mapped VCN %d to LCN %Xh (LBA %Xh)"%(self.start, self.vcn, lcn, self.boot.cl2offset(lcn))
                logging.debug("Chain%08X: mapped VCN %d to LCN %Xh (%d), LBA %Xh", int(self.start), self.vcn, int(lcn), lcn, int(self.boot.cl2offset(lcn)))
                logging.debug("Chain%08X: seeking cluster offset %Xh (%d)", int(self.start), int(self.vco), self.vco)
                self.stream.seek(self.boot.cl2offset(lcn)+self.vco)
                self.lastvlcn = (self.vcn, lcn)
                #~ print "Set lastvlcn", self.lastvlcn
                return
            vcn += count
            logging.debug("Chain%08X: reached chain's end seeking VCN %Xh", self.start, self.vcn)

    def read(self, size=-1):
        logging.debug("Chain%08X: read(%d) called from offset %Xh (%d)", self.start, size, self.pos, self.pos)
        # If negative size, set it to file size
        if size < 0:
            size = self.filesize
        # If requested size is greater than file size, limit to the latter
        if self.pos + size > self.filesize:
            size = self.filesize - self.pos
            if size < 0: size = 0
            logging.debug("Chain%08X: adjusted size is %d", self.start, size)
        buf = bytearray()
        if not size:
            logging.debug("Chain%08X: returning empty buffer", self.start)
            return buf
        if self.nofat: # contiguous clusters
            buf += self.stream.read(size)
            self.pos += size
            logging.debug("Chain%08X: read %d contiguous bytes @VCN %Xh [%X:%X]", self.start, len(buf), self.vcn, self.vco, self.vco+size)
            return buf
        while 1:
            if not size: break
            n = min(size, self.maxrun4len(size)-self.vco)
            buf += self.stream.read(n)
            size -= n
            self.pos += n
            logging.debug("Chain%08X: read %d (%d) bytes @VCN %Xh [%X:%X]", self.start, n, len(buf), self.vcn, self.vco, self.vco+n)
            self.seek(self.pos)
        return buf

    def write(self, s):
        if not s: return
        logging.debug("Chain%08X: write(buf[:%d]) called from offset %Xh (%d), VCN %Xh(%d)[%Xh:]", int(self.start), len(s), int(self.pos), self.pos, int(self.vcn), self.vcn, int(self.vco))
        new_allocated = 0
        if self.pos + len(s) > self.size:
            # Alloc more clusters from actual last one
            # reqb=requested bytes, reqc=requested clusters
            reqb = self.pos + len(s) - self.size
            reqc = rdiv(reqb, self.boot.cluster)
            logging.debug("pos=%X(%d), len=%d, size=%d(%Xh)", self.pos, self.pos, len(s), self.size, self.size)
            logging.debug("required %d byte(s) [%d cluster(s)] more to write", reqb, reqc)
            self._alloc(reqc)
            new_allocated = 1
        # force lastvlcn update (needed on allocation)
        self.seek(self.pos)
        if self.nofat: # contiguous clusters
            self.stream.write(s)
            logging.debug("Chain%08X: %d bytes fully written", self.start, len(s))
            self.pos += len(s)
            # file size is the top pos reached during write
            self.filesize = max(self.filesize, self.pos)
            return
        size=len(s) # bytes to do
        i=0 # pos in buffer
        while 1:
            if not size: break
            n = min(size, self.maxrun4len(size)-self.vco) # max bytes to complete run
            self.stream.write(s[i:i+n])
            size-=n
            i+=n
            self.pos += n
            logging.debug("Chain%08X: written %d bytes (%d of %d) @VCN %d [%Xh:%Xh]", self.start, n, i, len(s), self.vcn, self.vco, self.vco+n)
            self.seek(self.pos)
        self.filesize = max(self.filesize, self.pos)
        if new_allocated and (not self.fat.exfat or self.isdirectory):
            # When allocating a directory table, it is strictly necessary that only the first byte in
            # an empty slot (the first) is set to NULL
            if self.pos < self.size:
                logging.debug("Chain%08X: blanking newly allocated cluster tip, %d bytes @0x%X", self.start, self.size-self.pos, self.pos)
                self.stream.write(bytearray(self.size - self.pos))

    def trunc(self):
        "Truncates the clusters chain to the current one, freeing the rest"
        x = self.pos/self.boot.cluster # last VCN (=actual) to set
        n = rdiv(self.size, self.boot.cluster) - x - 1 # number of clusters to free
        logging.debug("%s: truncating @VCN %d, freeing %d clusters", self, x, n)
        if not n:
            logging.debug("nothing to truncate!")
            return 1
        #~ print "%s: truncating @VCN %d, freeing %d clusters. %d %d" % (self, x, n, self.pos, self.size)
        #~ print "Start runs:\n", self.runs
        # Updates chain and virtual stream sizes
        self.size = (x+1)*self.boot.cluster
        self.filesize = self.pos
        while 1:
            if not n: break
            start, length = self.runs.popitem()
            if n >= length:
                #~ print "Zeroing %d from %d" % (length, start)
                if self.fat.exfat:
                    self.boot.bitmap.free1(start, length)
                else:
                    self.fat.mark_run(start, length, True)
                if n == length and (not self.fat.exfat or len(self.runs) > 1):
                    k = self.runs.keys()[-1]
                    self.fat[k+self.runs[k]-1] = self.fat.last
                n -= length
            else:
                #~ print "Zeroing %d from %d, last=%d" % (n, start+length-n, start+length-n-1)
                if self.fat.exfat:
                    self.boot.bitmap.free1(start+length-n, n)
                else:
                    self.fat.mark_run(start+length-n, n, True)
                if len(self.runs) or not self.fat.exfat:
                    # Set new last cluster
                    self.fat[start+length-n-1] = self.fat.last
                self.runs[start] = length-n
                n=0
        #~ print "Final runs:\n", self.runs
        #~ for start, length in self.runs.items():
            #~ for i in range(length):
                #~ print "Cluster %d=%d"%(start+i, self.fat[start+i])
        self.nofat = (len(self.runs)==1)
        return 0

    def frags(self):
        logging.debug("Fragmentation of %s", self)
        logging.debug("Detected %d fragments for %d clusters", len(self.runs), self.size/self.boot.cluster)
        logging.debug("Fragmentation is %f", float(len(self.runs)-1) / float(self.size/self.boot.cluster))
        return len(self.runs)


class Handle(object):
    "Manage an open table slot"
    def __init__ (self):
        self.IsValid = False # determines whether update or not on disk
        self.File = None # file contents
        self.Entry = None # direntry slot
        self.Dir = None #dirtable owning the handle
        self.IsReadOnly = True # use this to prevent updating a Direntry on a read-only filesystem
        atexit.register(self.close) # forces close() on exit if user didn't call it

    def __del__ (self):
        self.close()

    def update_time(self, i=0):
        cdate, ctime = FATDirentry.GetDosDateTime()
        if i == 0:
            self.Entry.wADate = cdate
        elif i == 1:
            self.Entry.wMDate = cdate
            self.Entry.wMTime = ctime

    def tell(self):
        return self.File.tell()

    def seek(self, offset, whence=0):
        self.File.seek(offset, whence)

        self.Entry.dwFileSize = self.File.filesize
        self.Dir._update_dirtable(self.Entry)

    def read(self, size=-1):
        self.update_time()
        return self.File.read(size)

    def write(self, s):
        self.File.write(s)
        self.update_time(1)
        self.IsReadOnly = False

        self.Entry.dwFileSize = self.File.filesize
        self.Dir._update_dirtable(self.Entry)

    # NOTE: FAT permits chains with more allocated clusters than those required by file size!
    # Distinguish a ftruncate w/deallocation and update Chain.__init__ and Handle flushing accordingly!
    def ftruncate(self, length, free=0):
        "Truncates a file to a given size (eventually allocating more clusters), optionally unlinking clusters in excess."
        self.File.seek(length)
        self.File.filesize = length

        self.Entry.dwFileSize = self.File.filesize
        self.Dir._update_dirtable(self.Entry)

        if not free:
            return 0
        return self.File.trunc()

    def close(self):
        if not self.IsValid:
            return

        # Force setting the start cluster if allocated on write
        self.Entry.Start(self.File.start)

        if not self.Entry.IsDir():
            if self.Entry._buf[-32] == 0xE5 and self.Entry.Start():
                logging.debug("Deleted file: deallocating cluster(s)")
                self.File.fat.free(self.Entry.Start())
                # updates the Dirtable cache: mandatory if we allocated on write
                # (or start cluster won't be set)
                self.Dir._update_dirtable(self.Entry)
                return

            self.Entry.dwFileSize = self.File.filesize

        self.Dir.stream.seek(self.Entry._pos)
        logging.debug('Closing Handle @%Xh(%Xh) to "%s", cluster=%Xh tell=%d chain=%d size=%d', \
        int(self.Entry._pos), int(self.Dir.stream.realtell()), os.path.join(self.Dir.path,self.Entry.Name()), int(self.Entry.Start()), self.File.pos, self.File.size, self.File.filesize)
        logging.debug("!!!!!!!!!!!!!! handle: " + str(bytes(self.Entry.pack())))
        self.Dir.stream.write(self.Entry.pack())
        self.IsValid = False
        self.Dir._update_dirtable(self.Entry)

class Direntry(object):
    pass

DirentryType = type(Direntry())
HandleType = type(Handle())

class FATDirentry(Direntry):
    "Represents a FAT direntry of one or more slots"

    "Represents a 32 byte FAT (not exFAT) slot"
    layout = { # { offset: (name, unpack string) }
    0x00: ('sName', '8s'),
    0x08: ('sExt', '3s'),
    0x0B: ('chDOSPerms', 'B'),
    0x0C: ('chFlags', 'B'), # bit 3/4 set: lowercase basename/extension (NT)
    0x0D: ('chReserved', 'B'), # creation time fine resolution in 10 ms units, range 0-199
    0x0E: ('wCTime', '<H'),
    0x10: ('wCDate', '<H'),
    0x12: ('wADate', '<H'),
    0x14: ('wClusterHi', '<H'),
    0x16: ('wMTime', '<H'),
    0x18: ('wMDate', '<H'),
    0x1A: ('wClusterLo', '<H'),
    0x1C: ('dwFileSize', '<I') }

    "Represents a 32 byte FAT LFN slot"
    layout_lfn = { # { offset: (name, unpack string) }
    0x00: ('chSeqNumber', 'B'), # LFN slot #
    0x01: ('sName5', '10s'),
    0x0B: ('chDOSPerms', 'B'), # always 0xF
    0x0C: ('chType', 'B'), # always zero in VFAT LFN
    0x0D: ('chChecksum', 'B'),
    0x0E: ('sName6', '12s'),
    0x1A: ('wClusterLo', '<H'), # always zero
    0x1C: ('sName2', '4s') }

    def __init__ (self, s, pos=-1):
        self._i = 0
        self._buf = s
        self._pos = pos
        self._kv = {}
        for k in self.layout:
            self._kv[k-32] = self.layout[k]
        self._vk = {} # { name: offset}
        for k, v in self._kv.items():
            self._vk[v[0]] = k

    __getattr__ = common_getattr

    def pack(self):
        "Updates internal buffer"
        s = b''
        keys = self._kv.keys()
        list(keys).sort()
        for k in keys:
            v = self._kv[k]
            s += struct.pack(v[1], getattr(self, v[0]))
        self._buf[-32:] = bytearray(s) # update always non-LFN part
        return self._buf

    def __str__ (self):
        s = "FAT %sDirentry @%Xh\n" % ( ('','LFN ')[self.IsLfn()], self._pos )
        return class2str(self, s)

    def IsLfn(self):
        return self._buf[0x0B] == 0x0F and self._buf[0x0C] == self._buf[0x1A] == self._buf[0x1B] == 0

    def IsDeleted(self):
        return self._buf[0] == 0xE5

    def IsDir(self, value=-1):
        "Gets or sets the slot's Dir DOS permission"
        if value != -1:
            self._buf[-21] = value
        return (self._buf[-21] & 0x10) == 0x10

    def IsLabel(self, mark=0):
        "Gets or sets the slot's Label DOS permission"
        if mark:
            self._buf[0x0B] = 0x08
        return self._buf[0x0B] == 0x08

    def Start(self, cluster=None):
        "Gets or sets cluster WORDs in slot"
        if cluster != None:
            self.wClusterHi = cluster >> 16
            self.wClusterLo = cluster & 0xFFFF
        return (self.wClusterHi<<16) | self.wClusterLo

    def LongName(self):
        if not self.IsLfn():
            return ''
        i = len(self._buf)-64
        ln = ''
        while i >= 0:
            ln += self._buf[i+1:i+1+10].decode('utf-16le') + \
            self._buf[i+14:i+14+12].decode('utf-16le') + \
            self._buf[i+28:i+28+4].decode('utf-16le')
            i -= 32
        i = ln.find('\x00') # ending NULL may be omitted!
        if i < 0:
            return ln
        else:
            return ln[:i]

    def ShortName(self):
        return self.GenShortName(self._buf[-32:-21].decode(FS_ENCODING), self.chFlags)

    def Name(self):
        return self.LongName() or self.ShortName()

    @staticmethod
    def ParseDosDate(wDate):
        "Decodes a DOS date WORD into a tuple (year, month, day)"
        return (wDate>>9)+1980, (wDate>>5)&0xF, wDate&0x1F

    @staticmethod
    def ParseDosTime(wTime):
        "Decodes a DOS time WORD into a tuple (hour, minute, second)"
        return wTime>>11, (wTime>>5)&0x3F, wTime&0x1F

    @staticmethod
    def MakeDosTime(t):
        "Encodes a tuple (hour, minute, second) into a DOS time WORD"
        return (t[0] << 11) | (t[1] << 5) | (t[2]//2)

    @staticmethod
    def MakeDosDate(t):
        "Encodes a tuple (year, month, day) into a DOS date WORD"
        return ((t[0]-1980) << 9) | (t[1] << 5) | (t[2])

    @staticmethod
    def GetDosDateTime(format=0):
        "Returns a 2 WORDs tuple (DOSDate, DOSTime) or a DWORD, representing DOS encoding of current datetime"
        tm = time.localtime()
        cdate = ((tm[0]-1980) << 9) | (tm[1] << 5) | (tm[2])
        ctime = (tm[3] << 11) | (tm[4] << 5) | (tm[5]//2)
        if format:
            return ctime<<16 | cdate # DWORD
        else:
            return (cdate, ctime)

    @staticmethod
    def GenRawShortName(name):
        "Generates an old-style 8+3 DOS short name"
        name, ext = os.path.splitext(name)
        chFlags = 0
        if not ext and name in ('.', '..'): # special case
            name = '%-11s' % name
        elif 1 <= len(name) <= 8 and len(ext) <= 4:
            if ext and ext[0] == '.':
                ext = ext[1:]
            if name.islower():
                chFlags |= 8
            if ext.islower():
                chFlags |= 16
            name = '%-8s%-3s' % (name, ext)
            name = name.upper()
        logging.debug("GenRawShortName returned %s:%d",name,chFlags)
        return name, chFlags

    @staticmethod
    def GenShortName(shortname, chFlags=0):
        "Makes a human readable short name from slot's one"
        shortname=str(shortname)
        name = shortname[:8].rstrip()
        if chFlags & 0x8: name = name.lower()
        ext = shortname[8:].rstrip()
        if chFlags & 0x16: ext = ext.lower()
        logging.debug("GenShortName returned %s.%s",name,ext)
        if not ext: return name
        return name + '.' + ext

    @staticmethod
    def GenRawShortFromLongName(name, id=1):
        "Generates a DOS 8+3 short name from a long one (Windows 95 style)"
        # Replaces valid LFN chars prohibited in short name
        nname = name.replace(' ', '')
        # CAVE! Multiple dots?
        for c in '[]+,;=':
            nname = nname.replace(c, '_')
        nname, ext = os.path.splitext(nname)
        #~ print nname, ext
        # If no replacement and name is short (LIBs -> LIBS)
        if len(nname) < 9 and nname in name and ext in name:
            logging.debug("GenRawShortFromLongName (0) returned %s:%s",nname,ext[1:4])
            return (nname + ext[1:4]).upper()
        # Windows 9x: ~1 ... ~9999... as needed
        tilde = '~%d' % id
        i = 8 - len(tilde)
        if i > len(nname): i = len(nname)
        logging.debug("GenRawShortFromLongName (1) returned %s:%s",nname[:i]+tilde,ext[1:4])
        return (nname[:i] + tilde + ext[1:4]).upper()

    @staticmethod
    def GenRawShortFromLongNameNT(name, id=1):
        "Generates a DOS 8+3 short name from a long one (NT style)"
        if id < 5: return FATDirentry.GenRawShortFromLongName(name, id)
        #~ There's an higher probability of generating an unused alias at first
        #~ attempt, and an alias mathematically bound to its long name
        crc = crc32(name) & 0xFFFF
        longname = name
        name, ext = os.path.splitext(name)
        tilde = '~%d' % (id-4)
        i = 6 - len(tilde)
        # Windows NT 4+: ~1...~4; then: orig chars (1 or 2)+some CRC-16 (4 chars)+~1...~9
        # Expands tilde index up to 999.999 if needed like '95
        shortname = (name[:2] + hex(crc)[::-1][:i] + tilde + ext[1:4]).upper()
        logging.debug("Generated NT-style short name %s for %s", shortname, longname)
        return shortname

    def GenRawSlotFromName(self, shortname, longname=None):
        # Is presence of invalid (Unicode?) chars checked?
        shortname, chFlags = self.GenRawShortName(shortname)

        cdate, ctime = self.GetDosDateTime()

        self._buf = bytearray(struct.pack('<11s3B7HI', shortname.encode(), 0x20, chFlags, 0, ctime, cdate, cdate, 0, ctime, cdate, 0, 0))

        if longname:
            longname = longname.encode('utf-16le')
            if len(longname) > 510:
                raise Exception("Long name '%s' is >255 characters!" % longname)
            csum = self.Checksum(shortname)
            # If the last slot isn't filled, we must NULL terminate
            if len(longname) % 26:
                longname += b'\x00\x00'
            # And eventually pad with 0xFF, also
            if len(longname) % 26:
                longname += b'\xFF'*(26 - len(longname)%26)
            slots = len(longname)//26
            B=bytearray()
            while slots:
                b = bytearray(32)
                b[0] = slots
                j = (slots-1)*26
                b[1:11] = longname[j: j+10]
                b[11] = 0xF
                b[13] = csum
                b[14:27] = longname[j+10: j+22]
                b[28:32] = longname[j+22: j+26]
                B += b
                slots -= 1
            B[0] = B[0] | 0x40 # mark the last slot (first to appear)
            self._buf = B+self._buf

    @staticmethod
    def IsShortName(name):
        "Checks if name is an old-style 8+3 DOS short name"
        is_8dot3 = False
        name, ext = os.path.splitext(name)
        if not ext and name in ('.', '..'): # special case
            is_8dot3 = True
        # name.txt or NAME.TXT --> short
        # Name.txt or name.Txt etc. --> long (preserve case)
        # NT: NAME.txt or name.TXT or name.txt (short, bits 3-4 in 0x0C set accordingly)
        # tix8.4.3 --> invalid short (name=tix8.4, ext=.3)
        # dde1.3 --> valid short, (name=dde1, ext=.3)
        elif 1 <= len(name) <= 8 and len(ext) <= 4 and (name==name.upper() or name==name.lower()):
            if FATDirentry.IsValidDosName(name):
                is_8dot3 = True
        return is_8dot3

    special_short_chars = ''' "*/:<>?\|[]+.,;=''' + ''.join([chr(c) for c in range(32)])
    special_lfn_chars = '''"*/:<>?\|''' + ''.join([chr(c) for c in range(32)])

    @staticmethod
    def IsValidDosName(name, lfn=False):
        if name[0] == '\xE5': return False
        if lfn:
            special = FATDirentry.special_lfn_chars
        else:
            special = FATDirentry.special_short_chars
        for c in special:
            if c in name:
                return False
        return True

    def Match(self, name):
        "Checks if given short or long name matches with this slot's name"
        n =name.lower()
        # File.txt (LFN) == FILE.TXT == file.txt (short with special bits set) etc.
        if n == self.LongName().lower() or n == self.ShortName().lower(): return True
        return False

    @staticmethod
    def Checksum(name):
        "Calculates the 8+3 DOS short name LFN checksum"
        sum = 0
        for c in name:
            sum = ((sum & 1) << 7) + (sum >> 1) + ord(c)
            sum &= 0xff
        return sum

class Dirtable(object):
    "Manages a FAT12/16/32 directory table"
    dirtable = {} # {cluster: {'LFNs':{}, 'Names':{}}}

    def __init__(self, boot, fat, startcluster, size=0, path='.'):
        if type(boot) == HandleType:
            self.handle = boot # It's a directory handle
            self.boot = self.handle.File.boot
            self.fat = self.handle.File.fat
            self.start = self.handle.File.start
            self.stream = self.handle.File
        else:
            # non-zero size is a special case for fixed FAT12/16 root
            self.boot = boot
            self.fat = fat
            self.start = startcluster
        self.path = path
        self.needs_compact = 1


        tot, last = fat.count(startcluster)
        self.stream = Chain(boot, fat, startcluster, (boot.cluster*tot, size)[size>0], end=last)
        if startcluster not in Dirtable.dirtable:
            Dirtable.dirtable[startcluster] = {'LFNs':{}, 'Names':{}, 'Handle':None, 'slots_map':{}} # LFNs key MUST be Unicode!
        self.map_slots()

    def __str__(self):
        s = "Directory table @LCN %X (LBA %Xh)" % (self.start, self.boot.cl2offset(self.start))
        return s

    def getdiskspace(self):
        "Returns the disk free space in a tuple (clusters, bytes)"
        free_bytes = self.fat.free_clusters * self.boot.cluster
        return (self.fat.free_clusters, free_bytes)

    def open(self, name):
        "Opens the chain corresponding to an existing file name"
        res = Handle()
        if type(name) != DirentryType:
            root, fname = os.path.split(name)
            if root:
                root = self.opendir(root)
                if not root:
                    return res
            else:
                root = self
            e = root.find(fname)
        else:  # We assume it's a Direntry if not a string
            e = name
        if e:
            # Ensure it is not a directory or volume label
            if e.IsDir() or e.IsLabel():
                return res
            res.IsValid = True
            # If cluster is zero (empty file), then we must allocate one:
            # or Chain won't work!
            res.File = Chain(self.boot, self.fat, e.Start(), e.dwFileSize)
            res.Entry = e
            res.Dir = self
        return res

    def opendir(self, name):
        """Opens an existing relative directory path beginning in this table and
        return a new Dirtable object or None if not found"""
        name = name.replace('/', '\\')
        path = name.split('\\')
        found = self
        parent = self  # records parent dir handle
        for com in path:
            e = found.find(com)
            if e and e.IsDir():
                parent = found
                found = Dirtable(self.boot, self.fat, e.Start(), path=os.path.join(found.path, com))
                continue
            found = None
            break
        if found:
            logging.debug("Opened directory table '%s' @LCN %Xh (LBA %Xh)", found.path, found.start,
                              self.boot.cl2offset(found.start))
            if Dirtable.dirtable[found.start]['Handle']:
                # Opened many, closed once!
                found.handle = Dirtable.dirtable[found.start]['Handle']
                found.handle.IsValid = True
                logging.debug("retrieved previous directory Handle %s", found.handle)
                # We must update the Chain stream associated with the unique Handle,
                # or size variations will be discarded!
                found.stream = found.handle.File
            else:
                res = Handle()
                res.IsValid = True
                res.IsReadOnly = (self.boot.stream.mode != 'r+b')
                res.IsDirectory = 1
                res.File = found.stream
                res.File.isdirectory = 1
                res.Entry = e
                res.Dir = parent
                found.handle = res
                Dirtable.dirtable[found.start]['Handle'] = res
        return found

    def _alloc(self, name, clusters=0):
        "Allocates a new Direntry slot (both file/directory)"
        if len(os.path.join(self.path, name)) + 2 > 260:
            raise Exception("Can't add '%s' to directory table '%s', pathname >260!" % (name, self.path))
        dentry = FATDirentry(bytearray(32))
        # If name is a LFN, generate a short one valid in this table
        if not FATDirentry.IsShortName(name):
            i = 1
            short = FATDirentry.GenShortName(FATDirentry.GenRawShortFromLongNameNT(name, i))
            while self.find(short):
                i += 1
                short = FATDirentry.GenShortName(FATDirentry.GenRawShortFromLongNameNT(name, i))
            dentry.GenRawSlotFromName(short, name)
        else:
            dentry.GenRawSlotFromName(name)

        res = Handle()
        res.IsValid = True
        res.IsReadOnly = (self.boot.stream.mode != 'r+b')
        res.File = Chain(self.boot, self.fat, 0)
        if clusters:
            # Force clusters allocation
            res.File.seek(clusters * self.boot.cluster)
            res.File.seek(0)
        dentry._pos = self.findfree(len(dentry._buf))
        dentry.Start(res.File.start)
        res.Entry = dentry
        return res

    def create(self, name, prealloc=0):
        "Creates a new file chain and the associated slot. Erase pre-existing filename."
        e = self.open(name)
        if e.IsValid:
            e.IsValid = False
            self.erase(name)
        # Check if it is a supported name (=at least valid LFN)
        if not FATDirentry.IsValidDosName(name, True):
            raise Exception("Invalid characters in name '%s'" % name)
        handle = self._alloc(name, prealloc)
        self.stream.seek(handle.Entry._pos)
        self.stream.write(handle.Entry.pack())
        handle.Dir = self
        self._update_dirtable(handle.Entry)
        logging.debug("Created new file '%s' @%Xh", name, handle.File.start)
        return handle

    def mkdir(self, name):
        "Creates a new directory slot, allocating the new directory table"
        r = self.opendir(name)
        if r:
            logging.debug("mkdir('%s') failed, entry already exists!", name)
            return r
        # Check if it is a supported name (=at least valid LFN)
        if not FATDirentry.IsValidDosName(name, True):
            logging.debug("mkdir('%s') failed, name contains invalid chars!", name)
            return None
        handle = self._alloc(name, 1)
        self.stream.seek(handle.Entry._pos)
        handle.File.isdirectory = 1
        logging.debug("Making new directory '%s' @%Xh", name, handle.File.start)
        handle.Entry.chDOSPerms = 0x10
        self.stream.write(handle.Entry.pack())
        handle.Dir = self
        # PLEASE NOTE: Windows 10 opens a slot as directory and works regularly
        # even if table does not start with dot entries: but CHKDSK corrects it!
        # . in new table
        dot = FATDirentry(bytearray(32), 0)
        dot.GenRawSlotFromName('.')
        dot.Start(handle.Entry.Start())
        dot.chDOSPerms = 0x10
        handle.File.write(dot.pack())
        # .. in new table
        dot = FATDirentry(bytearray(32), 32)
        dot.GenRawSlotFromName('..')
        # Non-root parent's cluster # must be set
        if self.path != '.':
            dot.Start(self.stream.start)
        dot.chDOSPerms = 0x10
        handle.File.write(dot.pack())
        handle.File.write(bytearray(self.boot.cluster - 64))  # blank table
        self._update_dirtable(handle.Entry)
        handle.close()
        # Records the unique Handle to the directory
        Dirtable.dirtable[handle.File.start] = {'LFNs': {}, 'Names': {}, 'Handle': handle,
                                                'slots_map': {64: (2 << 20) / 32 - 2}}
        # ~ return Dirtable(handle, None, path=os.path.join(self.path, name))
        return self.opendir(name)

    def rmtree(self, name=None):
        "Removes a full directory tree"
        if name:
            logging.debug("rmtree:opening %s", name)
            target = self.opendir(name)
        else:
            target = self
        if not target:
            logging.debug("rmtree:target '%s' not found!", name)
            return 0
        for it in target.iterator():
            n = it.Name()
            if it.IsDir():
                if n in ('.', '..'): continue
                target.opendir(n).rmtree()
                logging.debug("rmtree:erasing '%s'", n)
            target.erase(n)
        del target
        if name:
            logging.debug("rmtree:erasing '%s'", name)
            self.erase(name)
        return 1

    def close(self, handle):
        "Updates a modified entry in the table"
        handle.close()

    def map_compact(self):
        "Compacts, eventually reordering, a slots map"
        if not self.needs_compact: return
        # ~ print "Map before:", sorted(Dirtable.dirtable[self.start]['slots_map'].iteritems())
        map_changed = 0
        while 1:
            M = Dirtable.dirtable[self.start]['slots_map']
            d = copy.copy(M)
            for k, v in sorted(M.items()):
                while d.get(k + 32 * v):  # while contig runs exist, merge
                    v1 = d.get(k + 32 * v)
                    logging.debug("Compacting map: {%d:%d} -> {%d:%d}", k, v, k, v + v1)
                    d[k] = v + v1
                    del d[k + 32 * v]
                    # ~ print "Compacted {%d:%d} -> {%d:%d}" %(k,v,k,v+v1)
                    # ~ print sorted(d.iteritems())
                    v += v1
            if Dirtable.dirtable[self.start]['slots_map'] != d:
                Dirtable.dirtable[self.start]['slots_map'] = d
                map_changed = 1
                continue
            break
        self.needs_compact = 0
        # ~ print "Map after:", sorted(Dirtable.dirtable[self.start]['slots_map'].iteritems())

    def map_slots(self):
        "Fills the free slots map and file names table once at first access"
        if not Dirtable.dirtable[self.start]['slots_map']:
            self.stream.seek(0)
            pos = 0
            s = ''
            while True:
                first_free = -1
                run_length = -1
                buf = bytearray()
                while True:
                    s = self.stream.read(32)
                    if not s or not s[0]: break
                    if s[0] == 0xE5:  # if erased
                        if first_free < 0:
                            first_free = pos
                            run_length = 0
                        run_length += 1
                        pos += 32
                        continue
                    # if not, and we record an erased slot...
                    if first_free > -1:
                        Dirtable.dirtable[self.start]['slots_map'][first_free] = run_length
                        first_free = -1
                    if s[0x0B] == 0x0F and s[0x0C] == s[0x1A] == s[0x1B] == 0:  # LFN
                        buf += s
                        pos += 32
                        continue
                    # if normal, in-use slot
                    buf += s
                    pos += 32
                    self._update_dirtable(FATDirentry(buf, pos - len(buf)))
                    buf = bytearray()
                if not s or not s[0]:
                    # Maps unallocated space to max table size
                    if self.path == '.' and hasattr(self, 'fixed_size'):  # FAT12/16 root
                        Dirtable.dirtable[self.start]['slots_map'][pos] = (self.fixed_size - pos) / 32
                    else:
                        Dirtable.dirtable[self.start]['slots_map'][pos] = ((2 << 20) - pos) / 32
                    break
            self.map_compact()
            logging.debug("%s collected slots map: %s", self, Dirtable.dirtable[self.start]['slots_map'])
            logging.debug("%s dirtable: %s", self, Dirtable.dirtable[self.start])

    # Assume table free space is zeroed
    def findfree(self, length=32):
        "Returns the offset of the first free slot or requested slot group size (in bytes)"
        length /= 32  # convert length in slots
        logging.debug("%s: findfree(%d) in map: %s", self, length, Dirtable.dirtable[self.start]['slots_map'])
        for start in sorted(Dirtable.dirtable[self.start]['slots_map']):
            rl = Dirtable.dirtable[self.start]['slots_map'][start]
            if length > 1 and length > rl: continue
            del Dirtable.dirtable[self.start]['slots_map'][start]
            if length < rl:
                Dirtable.dirtable[self.start]['slots_map'][start + 32 * length] = rl - length  # updates map
                logging.debug("%s: found free slot @%d, updated map: %s", self, start,
                              Dirtable.dirtable[self.start]['slots_map'])
            return start
        # FAT table limit is 2 MiB or 65536 slots (65534 due to "." and ".." entries)
        # So it can hold max 65534 files (all with short names)
        # FAT12&16 root have significantly smaller size (typically 224 or 512*32)
        raise Exception("Directory table of '%s' has reached its maximum extension!" % self.path)

    def iterator(self):
        "Iterates through directory table slots, generating a FATDirentry for each one"
        told = self.stream.tell()
        buf = bytearray()
        s = 1
        pos = 0
        while s:
            self.stream.seek(pos)
            s = self.stream.read(32)
            pos += 32
            if not s or s[0] == 0: break
            if s[0] == 0xE5: continue
            if s[0x0B] == 0x0F and s[0x0C] == s[0x1A] == s[0x1B] == 0:  # LFN
                buf += s
                continue
            buf += s
            yield FATDirentry(buf, self.stream.tell() - len(buf))
            buf = bytearray()
        self.stream.seek(told)

    def _update_dirtable(self, it, erase=False):
        "Updates internal cache of object names and their associated slots"
        if erase:
            del Dirtable.dirtable[self.start]['Names'][it.ShortName().lower()]
            ln = it.LongName()
            if ln:
                del Dirtable.dirtable[self.start]['LFNs'][ln.lower()]
            return
        Dirtable.dirtable[self.start]['Names'][it.ShortName().lower()] = it
        ln = it.LongName()
        if ln:
            Dirtable.dirtable[self.start]['LFNs'][ln.lower()] = it

    def find(self, name):
        "Finds an entry by name. Returns it or None if not found"
        # Create names cache
        if not Dirtable.dirtable[self.start]['Names']:
            self.map_slots()
        logging.debug("find: searching for %s (%s lower-cased)", name, name.lower())
        logging.debug("find: LFNs=%s", Dirtable.dirtable[self.start]['LFNs'])
        #name = name.decode(FS_ENCODING).lower()
        #name = str.encode(name.lower())
        name = name.lower()
        return Dirtable.dirtable[self.start]['LFNs'].get(name) or \
               Dirtable.dirtable[self.start]['Names'].get(name)

    def erase(self, name, force = False):
        "Marks a file's slot as erased and free the corresponding cluster chain"
        if type(name) == DirentryType:
            e = name
        else:
            e = self.find(name)
            if not e:
                return 0
        if e.IsDir():
            it = self.opendir(e.Name()).iterator()
            next(it)
            next(it)
            #it.next();
            #it.next()
            if next in it:
                logging.debug("Can't erase non empty directory slot @%d (pointing at #%d)", e._pos, e.Start())
                return 0
        start = e.Start()
        e.Start(0)
        e.dwFileSize = 0
        self._update_dirtable(e, True)
        for i in range(0, len(e._buf), 32):
            e._buf[i] = 0xE5

        if force:
            if not e.IsDir():
                dtInd = self.start
                self.handle.close()
                self.handle.IsValid = False
            else:
                dtInd = start
            # mkoll 26-08-18: invalidating handle, handle.close() silently overrides deleted entry
            Dirtable.dirtable[dtInd]['Handle'].IsValid = False
        self.stream.seek(e._pos)
        self.stream.write(e._buf)
        Dirtable.dirtable[self.start]['slots_map'][e._pos] = len(e._buf) / 32  # updates slots map
        self.map_compact()
        if start:
            self.fat.free(start)
        logging.debug("Erased slot '%s' @%Xh (pointing at LCN %Xh)", name, e._pos, start)
        logging.debug("Mapped new free slot {%d: %d}", e._pos, len(e._buf) / 32)
        return 1

    def rename(self, name, newname):
        "Renames a file or directory slot"
        if type(name) == DirentryType:
            e = name
        else:
            e = self.find(name)
            if not e:
                logging.debug("Can't find file to rename: '%'s", name)
                return 0
        if self.find(newname):
            logging.debug("Can't rename, file exists: '%s'", newname)
            return 0
        # Alloc new slot
        ne = self._alloc(newname)
        if not ne:
            logging.debug("Can't alloc new file slot for '%s'", newname)
            return 0
        # Copy attributes from old to new slot
        ne.Entry._buf[-21:] = e._buf[-21:]
        # Write new entry
        self.stream.seek(ne.Entry._pos)
        self.stream.write(ne.Entry._buf)
        ne.IsValid = False
        logging.debug("'%s' renamed to '%s'", name, newname)
        self._update_dirtable(ne.Entry)
        self._update_dirtable(e, True)
        # Mark the old one as erased
        for i in range(0, len(e._buf), 32):
            e._buf[i] = 0xE5
        self.stream.seek(e._pos)
        self.stream.write(e._buf)
        return 1

    @staticmethod
    def _sortby(a, b):
        "Helper function that sorts following the order in a list set by the caller in 'fix' variable."
        if a not in Dirtable._sortby.fix:
            return -1  # Unknown item comes first
        elif b not in Dirtable._sortby.fix:
            return 1
        else:
            return cmp(Dirtable._sortby.fix.index(a), Dirtable._sortby.fix.index(b))

    def clean(self, shrink=False):
        "Compacts used slots and blanks unused ones, optionally shrinking the table"
        logging.debug("Cleaning directory table %s with keep sort function", self.path)
        # ~ return self.sort(lambda x:x, shrink) # keep order
        return self.sort(None, shrink)  # keep order

    def stats(self):
        "Prints informations about slots in this directory table"
        in_use = 0
        count = 0
        for e in self.iterator():
            count += 1
            in_use += len(e._buf)
        print
        "%s: %d entries in %d slots on %d allocated" % (self.path, count, in_use / 32, self.stream.size / 32)

    def sort(self, by_func=None, shrink=False):
        """Sorts the slot entries alphabetically or applying by_func, compacting
        them and zeroing unused ones. Optionally shrinks table. Returns a tuple (used slots, blank slots)."""
        # CAVE! TABLE MUST NOT HAVE OPEN HANDLES!
        logging.debug("%s: table size at beginning: %d", self.path, self.stream.size)
        d = {}
        names = []
        for e in self.iterator():
            n = e.Name()
            if n in ('.', '..'): continue
            d[n] = e
            names += [n]
        # ~ names.sort(key=by_func)
        if by_func:
            names.sort(by_func)
        if self.path == '.':
            self.stream.seek(0)
        else:
            self.stream.seek(64)  # preserves dot entries
        for name in names:
            self.stream.write(d[name]._buf)  # re-writes ordered slots
        last = self.stream.tell()
        unused = self.stream.size - last
        self.stream.write(bytearray(unused))  # blank unused area
        logging.debug("%s: sorted %d slots, blanked %d", self.path, last / 32, unused / 32)
        if shrink:
            c_alloc = rdiv(self.stream.size, self.boot.cluster)
            c_used = rdiv(last, self.boot.cluster)
            if c_used < c_alloc:
                self.stream.seek(last)
                self.stream.trunc()
                logging.debug("Shrank directory table freeing %d clusters", c_alloc - c_used)
                unused -= (c_alloc - c_used / 32)
            else:
                logging.debug("Can't shrink directory table, free space < 1 cluster!")
        # Rebuilds Dirtable caches
        # ~ self.slots_map = {}
        # Rebuilds Dirtable caches
        Dirtable.dirtable[self.start] = {'LFNs': {}, 'Names': {}, 'Handle': None, 'slots_map': {}}
        self.map_slots()
        return last / 32, unused / 32

    def listdir(self):
        "Returns a list of file and directory names in this directory, sorted by on disk position"
        return map(lambda o: o.Name(), [o for o in self.iterator()])

    def list(self, bare=False):
        "Simple directory listing, with size and last modification time"
        print
        "   Directory of", self.path, "\n"
        tot_files = 0
        tot_bytes = 0
        tot_dirs = 0
        for it in self.iterator():
            if it.IsLabel(): continue
            if bare:
                print
                it.Name()
            else:
                tot_bytes += it.dwFileSize
                if it.IsDir():
                    tot_dirs += 1
                else:
                    tot_files += 1
                mtime = datetime(*(it.ParseDosDate(it.wMDate) + it.ParseDosTime(it.wMTime))).isoformat()[:-3].replace(
                    'T', ' ')
                print
                "%8s  %s  %s" % ((str(it.dwFileSize), '<DIR>')[it.IsDir()], mtime, it.Name())
        if not bare:
            print
            "%18s Files    %s bytes" % (tot_files, tot_bytes)
            print
            "%18s Directories %12s bytes free" % (tot_dirs, self.getdiskspace()[1])

    def walk(self):
        """Walks across this directory and its childs. For each visited directory,
        returns a tuple (root, dirs, files) sorted in disk order. """
        dirs = []
        files = []
        for o in self.iterator():
            if o.IsLabel(): continue
            n = o.Name()
            if n in ('.', '..'): continue
            if o.IsDir():
                dirs += [n]
            else:
                files += [n]
        yield self.path, dirs, files
        for subdir in dirs:
            for a, b, c in self.opendir(subdir).walk():
                yield a, b, c


def rdiv(a, b):
    "Divide a by b eventually rounding up"
    if a % b:
        return a // b + 1
    else:
        return a // b