# TODO
# Save videos to temporary folder until finished

from argparse import ArgumentParser, Namespace
from os import path
from signal import signal, SIGINT
from sys import exit
from time import sleep

from modules.Main import Main
from modules.Settings import Settings, ModelType, FrameType

parser: ArgumentParser = ArgumentParser()
parser.add_argument('-fps',     '--fps',        type=int,   default=20,     help='frames per second')
parser.add_argument('-pl',      '--players',    type=int,   default=6,      help='num players')
parser.add_argument('-mono',    '--mono',       action='store_true',        help='use left mono input instead of color')
parser.add_argument('-low',     '--lowres',     action='store_true',        help='low resolution mono (400p instead of 720p)')
parser.add_argument('-ss',      '--showstereo', action='store_true',        help='queue stereo frames')
parser.add_argument('-ll',      '--lightning',  action='store_true',        help='use low latency movenet model')
parser.add_argument('-st',      '--stereo',     action='store_true',        help='use stereo depth')
parser.add_argument('-ny',      '--noyolo',     action='store_true',        help='do not do yolo person detection')
parser.add_argument('-np',      '--nopose',     action='store_true',        help='do not do pose detection')
parser.add_argument('-cl',      '--chunklength',type=float, default=6.0,    help='duration of video chunks in seconds')
parser.add_argument('-sim',     '--simulation', action='store_true',        help='use prerecored video with camera')
parser.add_argument('-pt',      '--passthrough',action='store_true',        help='use prerecored video without camera')
args: Namespace = parser.parse_args()

currentPath: str = path.dirname(__file__)

camera_list: list[str] = ['14442C10F124D9D600',
                          '14442C10110AD3D200',
                          '14442C101136D1D200',
                          '14442C1031DDD2D200']

camera_list: list[str] = ['14442C10F124D9D600']

settings: Settings = Settings()
settings.root_path =    currentPath
settings.model_path =   path.join(currentPath, 'models')
settings.video_path =   path.join(currentPath, 'recordings')
settings.temp_path =    path.join(currentPath, 'temp')
settings.file_path =    path.join(currentPath, 'files')

settings.camera_list =  camera_list
settings.num_cams =     len(camera_list)
settings.fps =          args.fps
settings.color =    not args.mono
settings.stereo =       args.stereo
settings.lowres =       args.lowres
settings.person =   not args.noyolo
settings.show_stereo =  args.showstereo
settings.simulation =   args.simulation or args.passthrough
settings.passthrough =  args.passthrough

settings.num_players =  args.players
settings.pose =     not args.nopose
settings.model_type =   ModelType.NONE if args.nopose else ModelType.LIGHTNING if args.lightning else ModelType.THUNDER

settings.chunk_length = args.chunklength
settings.encoder =      Settings.CoderType.iGPU
settings.decoder =      Settings.CoderType.iGPU
settings.format =       Settings.CoderFormat.H264
settings.frame_types =  [FrameType.VIDEO, FrameType.LEFT_, FrameType.RIGHT] if settings.stereo else [FrameType.VIDEO]

settings.check_values()
settings.check_cameras()

app: Main = Main(settings)
app.start()

def signal_handler_exit(sig, frame) -> None:
    if app.isRunning():
        app.stop()
    exit()

signal(SIGINT, signal_handler_exit)

while app.isRunning():
    sleep(0.05)
    continue