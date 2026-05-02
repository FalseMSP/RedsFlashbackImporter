bl_info = {
    "name": "FlashBlack CJ/ET Blender Import",
    "author": "RedLife",
    "version": (1, 1, 0),
    "blender": (5, 0, 0),
    "location": "File > Import  |  3D View > Sidebar (N) > FlashBlack",
    "description": "Imports camera animation and tracking data from FlashBlack CJ/ET JSON files, sets end frame, converts Minecraft coordinates and rotations.",
    "category": "Import-Export",
}

import bpy
import json
import os
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty, FloatProperty, EnumProperty, BoolProperty, PointerProperty
import math
from mathutils import Quaternion, Vector


# Common video file extensions to search for
VIDEO_EXTENSIONS = [".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv", ".m4v", ".mts", ".m2ts"]


# ---------------------------------------------------------------------------
# Sidebar panel – Send object to Minecraft coordinates
# ---------------------------------------------------------------------------

class FlashBlackPanelProperties(bpy.types.PropertyGroup):
    mc_x: FloatProperty(name="MC X", description="Minecraft X coordinate", default=0.0)
    mc_y: FloatProperty(name="MC Y", description="Minecraft Y coordinate (vertical)", default=0.0)
    mc_z: FloatProperty(name="MC Z", description="Minecraft Z coordinate", default=0.0)
    block_size: FloatProperty(
        name="Block Size",
        description="Block size multiplier used during import",
        default=1.0,
        min=0.001,
    )
    target_object: PointerProperty(
        name="Object",
        description="Object to move to the Minecraft coordinates",
        type=bpy.types.Object,
    )
    # Stored at import time: the Blender-space position of the first camera keyframe.
    # Every subsequent coordinate conversion subtracts this so the scene stays
    # relative to the camera's new Blender origin (0, 0, 0).
    origin_offset_x: FloatProperty(name="Origin Offset X", default=0.0, options={'HIDDEN'})
    origin_offset_y: FloatProperty(name="Origin Offset Y", default=0.0, options={'HIDDEN'})
    origin_offset_z: FloatProperty(name="Origin Offset Z", default=0.0, options={'HIDDEN'})


class FLASHBLACK_OT_send_to_mc_coords(bpy.types.Operator):
    """Move the chosen object to the specified Minecraft world coordinates"""
    bl_idname = "flashblack.send_to_mc_coords"
    bl_label = "Send to Minecraft Coords"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.flashblack_props
        obj = props.target_object

        if obj is None:
            self.report({'ERROR'}, "No object selected.")
            return {'CANCELLED'}

        mc_x = props.mc_x
        mc_y = props.mc_y
        mc_z = props.mc_z
        bsm = props.block_size

        # Convert MC → Blender space (same formula as the importer)
        raw_loc = Vector((
            -(mc_x * bsm),
             (mc_z * bsm),
             (mc_y * bsm),
        ))

        # Subtract the origin offset that was stored at import time.
        # The camera's first keyframe was shifted to (0,0,0), so every
        # world coordinate must be shifted by the same amount.
        origin_offset = Vector((
            props.origin_offset_x,
            props.origin_offset_y,
            props.origin_offset_z,
        ))

        obj.location = raw_loc - origin_offset
        self.report({'INFO'}, f"Moved '{obj.name}' to MC ({mc_x}, {mc_y}, {mc_z})")
        return {'FINISHED'}


class FLASHBLACK_PT_sidebar(bpy.types.Panel):
    """FlashBlack tools in the N-panel sidebar"""
    bl_label = "FlashBlack"
    bl_idname = "FLASHBLACK_PT_sidebar"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "FlashBlack"

    def draw(self, context):
        layout = self.layout
        props = context.scene.flashblack_props

        layout.label(text="Send Object to MC Coords", icon='OBJECT_ORIGIN')
        layout.prop(props, "target_object")

        col = layout.column(align=True)
        col.prop(props, "mc_x")
        col.prop(props, "mc_y")
        col.prop(props, "mc_z")

        layout.prop(props, "block_size")
        layout.operator("flashblack.send_to_mc_coords", icon='EXPORT')


# ---------------------------------------------------------------------------
# Main importer
# ---------------------------------------------------------------------------

class FlashBlackImport(bpy.types.Operator, ImportHelper):
    """Import camera animation from a FlashBlack JSON file"""

    bl_idname = "import_anim.flashblack_json"
    bl_label = "Import FlashBlack CJ/ET"

    filename_ext = ".json"

    filter_glob: StringProperty(
        default="*.json",
        options={"HIDDEN"},
        maxlen=255,
    )

    import_type: EnumProperty(
        name="Import",
        description="Choose what to import from the FlashBlack JSON file.",
        items=(
            ('CJ', "CJ Camera", "Import camera animation data."),
            ('TJ', "TJ Animation", "Import entity animation data."),
            ('BOTH', "Both", "Import both camera and entity animation data."),
        ),
        default='BOTH',
    )

    block_size_multiplier: FloatProperty(
        name="Block Size Multiplier",
        description="Multiplier to scale the camera movement (e.g., 0.1 to reduce scale) // Usually it should stay at 1",
        default=1.0,
        min=0.001,
    )

    render_height: FloatProperty(
        name="Render Height",
        description="Height of Video",
        default=1600,
        min=1,
        max=50000,
    )

    render_width: FloatProperty(
        name="Render Width",
        description="Width of Video",
        default=3840,
        min=1,
        max=50000,
    )

    import_background_video: BoolProperty(
        name="Import Background Video",
        description="Automatically find and set a video file (same name as JSON) as the camera background",
        default=True,
    )

    def execute(self, context):
        cj_data = None
        tj_data = None
        success = True
        directory = os.path.dirname(self.filepath)
        base_name, ext = os.path.splitext(os.path.basename(self.filepath))

        modified_base_name = base_name[:-2] if len(base_name) >= 2 else base_name

        cj_filepath = os.path.join(directory, modified_base_name + "CJ" + ext)
        tj_filepath = os.path.join(directory, modified_base_name + "ET" + ext)

        if self.import_type == 'CJ' or self.import_type == 'BOTH':
            try:
                with open(cj_filepath, "r") as f:
                    cj_data = json.load(f)
            except FileNotFoundError:
                self.report({"ERROR"}, f"CJ JSON File not found: {cj_filepath}")
                success = False
            except json.JSONDecodeError:
                self.report({"ERROR"}, f"Invalid CJ JSON file: {cj_filepath}")
                success = False

        if self.import_type == 'TJ' or self.import_type == 'BOTH':
            try:
                with open(tj_filepath, "r") as f:
                    tj_data = json.load(f)
            except FileNotFoundError:
                self.report({"ERROR"}, f"ET JSON File not found: {tj_filepath}")
                success = False
            except json.JSONDecodeError:
                self.report({"ERROR"}, f"Invalid ET JSON file: {tj_filepath}")
                success = False

        if not success:
            return {"CANCELLED"}

        # Compute the origin offset from CJ data (or zero if CJ not being imported)
        if cj_data:
            origin_offset = self._compute_camera_origin_offset(cj_data, self.block_size_multiplier)
        else:
            origin_offset = Vector((0.0, 0.0, 0.0))

        if self.import_type == 'CJ' and cj_data:
            self.import_flashblack_animation(context, cj_data, self.block_size_multiplier, self.render_height, self.render_width, origin_offset)
        elif self.import_type == 'TJ' and tj_data:
            self.import_tracking_animation(context, tj_data, self.block_size_multiplier, origin_offset)
        elif self.import_type == 'BOTH' and cj_data and tj_data:
            self.import_flashblack_animation(context, cj_data, self.block_size_multiplier, self.render_height, self.render_width, origin_offset)
            self.import_tracking_animation(context, tj_data, self.block_size_multiplier, origin_offset)
        elif self.import_type == 'BOTH' and (not cj_data or not tj_data):
            self.report({"ERROR"}, "Both CJ and ET JSON files are required for 'Both' import.")
            return {"CANCELLED"}

        # Sync sidebar block size to whatever was used for import
        context.scene.flashblack_props.block_size = self.block_size_multiplier

        # Import background video after camera is set up
        if self.import_background_video and (self.import_type in ('CJ', 'BOTH')):
            video_path = self.find_video_file(directory, modified_base_name)
            if video_path:
                self.set_background_video(context, video_path)
                self.report({"INFO"}, f"Background video set: {os.path.basename(video_path)}")
            else:
                self.report({"WARNING"}, f"No video file found matching '{modified_base_name}' in {directory}")

        return {"FINISHED"}

    def find_video_file(self, directory, base_name):
        """Search for a video file in the directory matching the base name."""
        for video_ext in VIDEO_EXTENSIONS:
            candidate = os.path.join(directory, base_name + video_ext)
            if os.path.isfile(candidate):
                return candidate
        return None

    def set_background_video(self, context, video_path):
        """Load a video and set it as the background on the active camera."""
        camera_object = context.scene.camera
        if not camera_object or camera_object.type != 'CAMERA':
            self.report({"WARNING"}, "No active camera found to attach background video to.")
            return

        camera_data = camera_object.data

        clip_name = os.path.basename(video_path)

        existing_clip = bpy.data.movieclips.get(clip_name)
        if existing_clip:
            movie_clip = existing_clip
        else:
            movie_clip = bpy.data.movieclips.load(video_path)

        # Remove any existing background images on the camera to avoid duplicates
        for bg in list(camera_data.background_images):
            camera_data.background_images.remove(bg)

        bg = camera_data.background_images.new()
        bg.source = 'MOVIE_CLIP'
        bg.clip = movie_clip
        bg.display_depth = 'BACK'
        bg.frame_method = 'STRETCH'
        bg.alpha = 1.0

        camera_data.show_background_images = True

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "import_type")
        layout.prop(self, "block_size_multiplier")

        if self.import_type in ('CJ', 'BOTH'):
            layout.prop(self, "render_width")
            layout.prop(self, "render_height")
            layout.prop(self, "import_background_video")

    # ------------------------------------------------------------------
    # Sun light helpers
    # ------------------------------------------------------------------

    def get_or_create_sun_light(self):
        """Return the 'MC_Sun' sun light, creating it if it doesn't exist yet."""
        obj = bpy.data.objects.get("MC_Sun")
        if obj and obj.type == 'LIGHT' and obj.data.type == 'SUN':
            return obj

        light_data = bpy.data.lights.new(name="MC_Sun", type='SUN')
        light_data.energy = 5.0
        light_data.angle = math.radians(0.526)

        obj = bpy.data.objects.new("MC_Sun", light_data)
        bpy.context.collection.objects.link(obj)
        obj.location = (0.0, 0.0, 0.0)
        return obj

    def minecraft_time_to_sun_rotation(self, mc_time):
        angle = (mc_time / 24000.0) * (2.0 * math.pi) - (math.pi / 2.0)
        return (0.0, angle, 0.0)

    def keyframe_sun(self, sun_obj, mc_time, blender_frame):
        sun_obj.rotation_mode = 'XYZ'
        sun_obj.rotation_euler = self.minecraft_time_to_sun_rotation(mc_time)
        sun_obj.keyframe_insert(data_path="rotation_euler", frame=blender_frame)

        sun_angle_rad = (mc_time / 24000.0) * (2.0 * math.pi)
        brightness_factor = max(0.0, math.sin(sun_angle_rad))
        sun_obj.data.energy = 5.0 * brightness_factor
        sun_obj.data.keyframe_insert(data_path="energy", frame=blender_frame)

    # ------------------------------------------------------------------
    # Camera import – with origin offset
    # ------------------------------------------------------------------

    def _compute_camera_origin_offset(self, data, block_size_multiplier):
        """
        Return the Blender-space location of the very first camera keyframe so
        that we can subtract it from every keyframe, making the camera start at
        Blender (0, 0, 0).  Returns a Vector(0,0,0) when no position data exists.
        """
        keyframes = data.get("keyframes", [])
        if not keyframes:
            return Vector((0.0, 0.0, 0.0))

        first = keyframes[0]
        if "position" not in first:
            return Vector((0.0, 0.0, 0.0))

        mc_x, mc_y, mc_z = first["position"]
        bsm = block_size_multiplier
        blender_x = mc_x * bsm
        blender_y = -mc_z * bsm
        blender_z = mc_y * bsm
        # The actual location applied is (-blender_x, -blender_y, blender_z)
        return Vector((-blender_x, -blender_y, blender_z))

    def import_flashblack_animation(self, context, data, block_size_multiplier, render_height, render_width, origin_offset=None):
        """Imports camera animation data from the parsed JSON."""
        if origin_offset is None:
            origin_offset = self._compute_camera_origin_offset(data, block_size_multiplier)

        max_frame = 0

        camera_data = bpy.data.cameras.new(name="ImportedCameraData")
        new_camera = bpy.data.objects.new("CJ Camera", camera_data)
        bpy.context.collection.objects.link(new_camera)

        bpy.context.scene.camera = new_camera

        if not new_camera.animation_data:
            new_camera.animation_data_create()

        # Persist the offset so the sidebar "Send to MC Coords" operator can use it
        context.scene.flashblack_props.origin_offset_x = origin_offset.x
        context.scene.flashblack_props.origin_offset_y = origin_offset.y
        context.scene.flashblack_props.origin_offset_z = origin_offset.z

        sun_light = self.get_or_create_sun_light()

        if "keyframes" in data:
            for frame_number, keyframe_data in enumerate(data["keyframes"]):
                blender_frame = frame_number + 1
                self.import_keyframe(
                    context,
                    new_camera,
                    keyframe_data,
                    block_size_multiplier,
                    blender_frame,
                    render_width,
                    render_height,
                    origin_offset,
                )

                if "time" in keyframe_data:
                    try:
                        mc_time = float(keyframe_data["time"]) % 24000.0
                        self.keyframe_sun(sun_light, mc_time, blender_frame)
                    except (TypeError, ValueError) as e:
                        self.report({"WARNING"}, f"Invalid 'time' value at frame {blender_frame}: {e}")

                max_frame = max(max_frame, blender_frame)

        bpy.context.scene.frame_end = int(max_frame)

    def import_keyframe(self, context, camera_object, keyframe_data, block_size_multiplier,
                        frame, render_width, render_height, origin_offset=None):
        """Imports position, rotation, and FOV data for a specific frame."""
        if origin_offset is None:
            origin_offset = Vector((0.0, 0.0, 0.0))

        try:
            if "position" in keyframe_data:
                mc_x, mc_y, mc_z = keyframe_data["position"]

                blender_x = mc_x * block_size_multiplier
                blender_y = -mc_z * block_size_multiplier
                blender_z = mc_y * block_size_multiplier

                # Subtract the first-frame offset so the camera starts at (0,0,0)
                raw_loc = Vector((-blender_x, -blender_y, blender_z))
                camera_object.location = raw_loc - origin_offset
                camera_object.keyframe_insert(data_path="location", frame=frame)

            if (
                "w" in keyframe_data
                and "x" in keyframe_data
                and "y" in keyframe_data
                and "z" in keyframe_data
            ):
                camera_object.rotation_mode = 'QUATERNION'
                minecraft_quat = Quaternion((
                    keyframe_data["w"],
                    keyframe_data["x"],
                    keyframe_data["y"],
                    keyframe_data["z"]
                ))

                correction = Quaternion((0.0, 0.0, -0.7071068, -0.7071068))
                camera_object.rotation_quaternion = correction @ minecraft_quat
                camera_object.keyframe_insert(data_path="rotation_quaternion", frame=frame)

            elif (
                "yaw" in keyframe_data
                and "pitch" in keyframe_data
                and "roll" in keyframe_data
            ):
                yaw_degrees = keyframe_data["yaw"]
                pitch_degrees = keyframe_data["pitch"]
                roll_degrees = keyframe_data["roll"]

                camera_object.rotation_mode = 'XYZ'

                blender_pitch = math.radians(-pitch_degrees + 90)
                blender_yaw = math.radians(-yaw_degrees)
                blender_roll = math.radians(-roll_degrees)

                camera_object.rotation_euler = (blender_pitch, blender_roll, blender_yaw)
                camera_object.keyframe_insert(data_path="rotation_euler", frame=frame)

            if "fov" in keyframe_data:
                fov_degrees = keyframe_data["fov"]

                if 0 < fov_degrees < 180:
                    camera_object.data.lens_unit = 'MILLIMETERS'
                    camera_object.data.sensor_fit = 'VERTICAL'

                    sensor_height_mm = camera_object.data.sensor_height
                    focal_length = sensor_height_mm / (2 * math.tan(math.radians(fov_degrees) / 2))

                    camera_object.data.lens = focal_length
                    camera_object.data.keyframe_insert(data_path="lens", frame=frame)

        except ValueError as e:
            self.report({"WARNING"}, f"Error processing keyframe at frame {frame}: {e}")
        except Exception as e:
            self.report({"ERROR"}, f"Error processing keyframe: {e}")

    def import_tracking_animation(self, context, data, block_size_multiplier, origin_offset=None):
        """Imports entity tracking animation data from the parsed JSON."""
        if origin_offset is None:
            origin_offset = Vector((0.0, 0.0, 0.0))

        if 'Entities' not in data:
            self.report({"ERROR"}, "TJ JSON file does not contain 'Entities' data.")
            return

        max_frame = 0

        for frame_data in data['Entities']:
            for entity_name, entity_parts in frame_data.items():
                if entity_name == 'tick':
                    continue

                tick = frame_data.get('tick', -1)
                if tick == -1:
                    self.report({"WARNING"}, f"Frame missing 'tick' information: {frame_data}")
                    continue

                frame_number = int(tick) + 1

                parent_empty_name = f"{entity_name}_Animation"
                parent_empty = bpy.data.objects.get(parent_empty_name)
                if not parent_empty or parent_empty.type != 'EMPTY':
                    parent_empty = bpy.data.objects.new(parent_empty_name, None)
                    bpy.context.collection.objects.link(parent_empty)

                for part_name_json, transform_data in entity_parts.items():
                    if part_name_json.lower() == "eyes":
                        eye_position = transform_data.get("eyePosition")
                        if eye_position:
                            eye_empty_name = f"{parent_empty_name}_eyePosition"
                            eye_empty = bpy.data.objects.get(eye_empty_name)
                            if not eye_empty or eye_empty.type != 'EMPTY':
                                eye_empty = bpy.data.objects.new(eye_empty_name, None)
                                bpy.context.collection.objects.link(eye_empty)

                            ex, ey, ez = eye_position
                            blender_x = ex * block_size_multiplier
                            blender_y = -ez * block_size_multiplier
                            blender_z = ey * block_size_multiplier

                            raw_loc = Vector((-blender_x, -blender_y, blender_z))
                            eye_empty.location = raw_loc - origin_offset
                            eye_empty.keyframe_insert(data_path="location", frame=frame_number)

                            eye_angle_data = transform_data.get("eyeangle")
                            if eye_angle_data and len(eye_angle_data) == 3:
                                blender_pitch = math.radians(-eye_angle_data[0])
                                blender_yaw = math.radians(-eye_angle_data[1])
                                blender_roll = math.radians(eye_angle_data[2])
                                eye_empty.rotation_mode = 'XYZ'
                                eye_empty.rotation_euler = (blender_pitch, blender_roll, blender_yaw)
                                eye_empty.keyframe_insert(data_path="rotation_euler", frame=frame_number)

                    elif part_name_json.lower() == "blockposition":
                        block_position = transform_data.get("blockPosition")
                        if block_position:
                            bp_x, bp_y, bp_z = block_position
                            blender_x = bp_x * block_size_multiplier
                            blender_y = -bp_z * block_size_multiplier
                            blender_z = bp_y * block_size_multiplier

                            raw_loc = Vector((-blender_x, -blender_y, blender_z))
                            parent_empty.location = raw_loc - origin_offset
                            parent_empty.keyframe_insert(data_path="location", frame=frame_number)

                    else:
                        rotation = transform_data.get("rotation")
                        position = transform_data.get("position")

                        empty_object_name = f"{parent_empty_name}_{part_name_json}"
                        empty_object = bpy.data.objects.get(empty_object_name)
                        if not empty_object or empty_object.type != 'EMPTY':
                            empty_object = bpy.data.objects.new(empty_object_name, None)
                            bpy.context.collection.objects.link(empty_object)
                            empty_object.parent = parent_empty

                        if position:
                            px, py, pz = position
                            empty_object.location = (px * block_size_multiplier, py * block_size_multiplier, pz * block_size_multiplier)
                            empty_object.keyframe_insert(data_path="location", frame=frame_number)

                        if rotation:
                            rotation_rad = [r for r in rotation]

                            yaw_rad = rotation_rad[2]
                            pitch_rad = rotation_rad[0]
                            roll_rad = rotation_rad[1]

                            empty_object.rotation_mode = 'XYZ'

                            blender_pitch = -pitch_rad
                            blender_yaw = -yaw_rad
                            blender_roll = roll_rad

                            empty_object.rotation_euler = (blender_pitch, blender_yaw, -blender_roll)
                            empty_object.keyframe_insert(data_path="rotation_euler", frame=frame_number)

                max_frame = max(max_frame, frame_number)

        bpy.context.scene.frame_end = max(bpy.context.scene.frame_end, max_frame)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def menu_func_import(self, context):
    self.layout.operator(FlashBlackImport.bl_idname, text="FlashBlack Camera/Tracking (.json)")


_classes = (
    FlashBlackPanelProperties,
    FLASHBLACK_OT_send_to_mc_coords,
    FLASHBLACK_PT_sidebar,
    FlashBlackImport,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.flashblack_props = PointerProperty(type=FlashBlackPanelProperties)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    del bpy.types.Scene.flashblack_props
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()