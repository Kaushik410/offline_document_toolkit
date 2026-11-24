"""Image operations shared by the desktop preview and batch services."""
from pathlib import Path
import io

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, TiffImagePlugin

from utils.output_utils import atomic_output


class ImageService:
    SUPPORTED_INPUTS = ['.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff']
    FORMATS = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG', '.webp': 'WEBP',
               '.bmp': 'BMP', '.tif': 'TIFF', '.tiff': 'TIFF'}

    @staticmethod
    def _validate_image(file_path):
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f'Image not found: {file_path}')
        if path.suffix.lower() not in ImageService.SUPPORTED_INPUTS:
            raise ValueError(f'Unsupported image file: {file_path}')
        return path

    @staticmethod
    def _prepare_output_path(output_file, default_ext='.png'):
        path = Path(output_file)
        if not path.suffix:
            path = path.with_suffix(default_ext)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def load_frames(input_file):
        frames = []
        with Image.open(ImageService._validate_image(input_file)) as image:
            for index in range(getattr(image, 'n_frames', 1)):
                image.seek(index)
                frame = ImageOps.exif_transpose(image).copy()
                # TIFF resolution belongs to each page, not just to the first IFD.
                if hasattr(image, 'tag_v2'):
                    frame.tag_v2 = TiffImagePlugin.ImageFileDirectory_v2()
                    for key in (282, 283, 296):
                        if key in image.tag_v2:
                            frame.tag_v2[key] = image.tag_v2[key]
                frames.append(frame)
        return frames

    @staticmethod
    def load_image(input_file, allow_multiframe=False):
        with Image.open(ImageService._validate_image(input_file)) as image:
            count = getattr(image, 'n_frames', 1)
            if count > 1 and not allow_multiframe:
                raise ValueError('This tool edits a single image. Split the multi-page TIFF first, '
                                 'or use compression to preserve all pages.')
            result = ImageOps.exif_transpose(image).copy()
            if result.mode == 'CMYK':
                result = result.convert('RGB')
            result.info['odt_frame_count'] = count
            return result

    @staticmethod
    def to_rgb(image):
        """Flatten alpha and palette transparency onto a white document background."""
        if 'A' in image.getbands() or 'transparency' in image.info:
            rgba = image.convert('RGBA')
            return Image.alpha_composite(Image.new('RGBA', rgba.size, 'white'), rgba).convert('RGB')
        return image.convert('RGB')

    @staticmethod
    def encode_image(image, suffix, quality=None):
        return ImageService.encode_frames([image], suffix, quality)

    @staticmethod
    def encode_frames(frames, suffix, quality=None):
        suffix = suffix.lower()
        if suffix not in ImageService.FORMATS:
            raise ValueError(f'Unsupported output format: {suffix}')
        if quality is not None and not 1 <= quality <= 100:
            raise ValueError('Quality must be between 1 and 100.')
        if not frames:
            raise ValueError('No image pages to save.')
        if len(frames) > 1 and suffix not in ('.tif', '.tiff'):
            raise ValueError('The selected format cannot preserve multiple pages. Choose TIFF.')
        image = frames[0]
        options = {}
        if suffix in ('.jpg', '.jpeg', '.bmp') and image.mode not in ('RGB', 'L'):
            image = ImageService.to_rgb(image)
        elif suffix in ('.png', '.webp') and image.mode == 'CMYK':
            image = image.convert('RGB')
        if quality is not None:
            if suffix in ('.jpg', '.jpeg'):
                options = {'quality': quality, 'optimize': True}
            elif suffix == '.webp':
                options = {'quality': quality, 'method': 6}
            elif suffix == '.png':
                options = {'optimize': True, 'compress_level': 9}
            elif suffix in ('.tif', '.tiff'):
                options = {'compression': 'tiff_deflate'}
        if suffix in ('.tif', '.tiff'):
            options.update(save_all=True, append_images=frames[1:])
        buffer = io.BytesIO()
        image.save(buffer, format=ImageService.FORMATS[suffix], **options)
        return buffer.getvalue()

    @staticmethod
    def save_image(image, output_file, quality=None):
        return ImageService.save_frames([image], output_file, quality)

    @staticmethod
    def save_frames(frames, output_file, quality=None):
        output = ImageService._prepare_output_path(output_file)
        data = ImageService.encode_frames(frames, output.suffix, quality)
        with atomic_output(output) as temporary:
            temporary.write_bytes(data)
        return str(output)

    @staticmethod
    def edit_image(image, operation, **params):
        image = image.copy()
        if operation == 'resize':
            width, height = params['width'], params['height']
            if width <= 0 or height <= 0:
                raise ValueError('Width and height must be positive.')
            if params.get('keep_aspect', True):
                image = ImageOps.contain(image, (width, height), Image.Resampling.LANCZOS)
            else:
                image = image.resize((width, height), Image.Resampling.LANCZOS)
        elif operation == 'rotate':
            if params['angle'] not in (90, 180, 270):
                raise ValueError('Angle must be 90, 180, or 270 degrees.')
            image = image.rotate(-params['angle'], expand=True)
        elif operation == 'flip':
            if params['direction'] not in ('horizontal', 'vertical'):
                raise ValueError('Direction must be horizontal or vertical.')
            image = ImageOps.mirror(image) if params['direction'] == 'horizontal' else ImageOps.flip(image)
        elif operation == 'black_white':
            image = image.convert('L')
        elif operation == 'brightness_contrast':
            if params['brightness'] <= 0 or params['contrast'] <= 0:
                raise ValueError('Brightness and contrast must be positive.')
            image = ImageEnhance.Brightness(image).enhance(params['brightness'])
            image = ImageEnhance.Contrast(image).enhance(params['contrast'])
        elif operation == 'sharpen':
            if params['factor'] <= 0:
                raise ValueError('Sharpen factor must be positive.')
            image = ImageEnhance.Sharpness(image).enhance(params['factor'])
        elif operation == 'denoise':
            strength = params['strength']
            if not 1 <= strength <= 30:
                raise ValueError('Denoise strength must be between 1 and 30.')
            source = cv2.cvtColor(np.array(image.convert('RGB')), cv2.COLOR_RGB2BGR)
            result = cv2.fastNlMeansDenoisingColored(source, None, strength, strength, 7, 21)
            image = Image.fromarray(cv2.cvtColor(result, cv2.COLOR_BGR2RGB))
        elif operation in ('crop', 'blur'):
            left, top, right, bottom = params['rect']
            if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
                raise ValueError('Select a nonempty area inside the image.')
            if operation == 'crop':
                image = image.crop((left, top, right, bottom))
            else:
                radius = params.get('blur_radius', 12)
                if radius <= 0:
                    raise ValueError('Blur radius must be positive.')
                area = image.crop((left, top, right, bottom)).filter(ImageFilter.GaussianBlur(radius))
                image.paste(area, (left, top))
        elif operation == 'add_text':
            if not params['text'].strip() or params['font_size'] <= 0:
                raise ValueError('Enter text and a positive font size.')
            image = image.convert('RGBA')
            try:
                font = ImageFont.truetype('DejaVuSans-Bold.ttf', params['font_size'])
            except OSError:
                font = ImageFont.load_default(size=params['font_size'])
            ImageDraw.Draw(image).text((params['x'], params['y']), params['text'],
                                      font=font, fill=(255, 0, 0, 255))
        elif operation not in ('compress', 'convert_format'):
            raise ValueError(f'Unknown image operation: {operation}')
        return image

    @staticmethod
    def preview_image(input_file, operation, params, base_image=None):
        size = None
        if operation == 'compress':
            frames = ImageService.load_frames(input_file)
            size = len(ImageService.encode_frames(frames, Path(input_file).suffix, params['quality']))
            image = frames[0].convert('RGB') if frames[0].mode == 'CMYK' else frames[0].copy()
        else:
            source = base_image if base_image is not None else ImageService.load_image(input_file)
            image = ImageService.edit_image(source, operation, **params)
        return image, size

    @staticmethod
    def _apply(input_file, output_file, operation, **params):
        path = ImageService._validate_image(input_file)
        output = ImageService._prepare_output_path(output_file, path.suffix)
        image = ImageService.edit_image(ImageService.load_image(path), operation, **params)
        return ImageService.save_image(image, output)

    @staticmethod
    def resize_image(input_file, output_file, width, height, keep_aspect=True):
        return ImageService._apply(input_file, output_file, 'resize', width=width, height=height, keep_aspect=keep_aspect)

    @staticmethod
    def compress_image(input_file, output_file, quality=70):
        path = ImageService._validate_image(input_file)
        original_size = path.stat().st_size
        output = ImageService._prepare_output_path(output_file, path.suffix)
        ImageService.save_frames(ImageService.load_frames(path), output, quality=quality)
        return str(output), original_size, output.stat().st_size

    @staticmethod
    def convert_format(input_file, output_file, output_format, overwrite=False):
        output_format = output_format.lower()
        if output_format not in ('png', 'jpg', 'jpeg', 'webp', 'bmp', 'tiff'):
            raise ValueError('Invalid output format.')
        output = Path(output_file).with_suffix('.jpg' if output_format == 'jpeg' else '.' + output_format)
        if output.resolve() != Path(output_file).resolve() and output.exists() and not overwrite:
            raise FileExistsError(f'Format conversion would overwrite a different file: {output}')
        return ImageService.save_frames(ImageService.load_frames(input_file), output)

    @staticmethod
    def rotate_image(input_file, output_file, angle):
        return ImageService._apply(input_file, output_file, 'rotate', angle=angle)

    @staticmethod
    def flip_image(input_file, output_file, direction):
        return ImageService._apply(input_file, output_file, 'flip', direction=direction)

    @staticmethod
    def black_and_white(input_file, output_file):
        return ImageService._apply(input_file, output_file, 'black_white')

    @staticmethod
    def adjust_brightness_contrast(input_file, output_file, brightness=1.0, contrast=1.0):
        return ImageService._apply(input_file, output_file, 'brightness_contrast', brightness=brightness, contrast=contrast)

    @staticmethod
    def sharpen_image(input_file, output_file, factor=2.0):
        return ImageService._apply(input_file, output_file, 'sharpen', factor=factor)

    @staticmethod
    def denoise_image(input_file, output_file, strength=10):
        return ImageService._apply(input_file, output_file, 'denoise', strength=strength)

    @staticmethod
    def crop_image(input_file, output_file, left, top, right, bottom):
        return ImageService._apply(input_file, output_file, 'crop', rect=(left, top, right, bottom))

    @staticmethod
    def add_text(input_file, output_file, text, x, y, font_size=32):
        return ImageService._apply(input_file, output_file, 'add_text', text=text, x=x, y=y, font_size=font_size)

    @staticmethod
    def blur_area(input_file, output_file, left, top, right, bottom, blur_radius=12):
        return ImageService._apply(input_file, output_file, 'blur', rect=(left, top, right, bottom), blur_radius=blur_radius)
