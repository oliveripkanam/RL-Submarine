from src.cave_environment.environment import CaveEnvironment
from src.cave_environment.spritesheet import SpriteSheet
from Submarine import Submarine
import pygame
import pymunk
import math
from pygame.locals import *
from sonar_sensors import Sonar

pygame.init()
DISPLAY_WIDTH, DISPLAY_HEIGHT = 60 * 16, 40 * 16
screen = pygame.display.set_mode((DISPLAY_WIDTH, DISPLAY_HEIGHT))
canvas = pygame.Surface((DISPLAY_WIDTH, DISPLAY_HEIGHT))

spritesheet = SpriteSheet("src/cave_environment/tileset.png")
font = pygame.font.Font(None, 25)

# Map files list
map_files = [
    "src/cave_environment/tileset_basic.csv",
    "src/cave_environment/tileset_editor_basic_jagged.csv",
    "src/cave_environment/tileset_jagged_narrow.csv",
    "src/cave_environment/tileset_right_angle.csv",
    "src/cave_environment/tileset_right_angle_x_axis_flipped.csv",
    "src/cave_environment/tileset_right_angle_x_y_axis_flipped.csv",
    "src/cave_environment/tileset_right_angle_y_axis_flipped.csv"
]
current_map_index = 0

def find_safe_start(env, width, height):
    wall_rects = [t.rect for t in env.environment_tiles]
    for y in range(100, height - 100, 50):
        for x in range(100, width - 100, 50):
            test_rect = pygame.Rect(x, y, 40, 40)
            if test_rect.collidelist(wall_rects) == -1:
                return x, y
    return 100, 100

def load_level(map_index):
    new_space = pymunk.Space()
    actual_index = map_index
    
    try:
        if map_index >= len(map_files):
            print(f"Map index {map_index} not found, defaulting to 0")
            actual_index = 0
            
        env = CaveEnvironment(map_files[actual_index], spritesheet)
        
        for tile in env.environment_tiles:
            body = pymunk.Body(body_type=pymunk.Body.STATIC)
            body.position = (tile.rect.centerx, tile.rect.centery)
            shape = pymunk.Poly.create_box(body, (16, 16))
            shape.elasticity = 0.0
            shape.friction = 0.0
            new_space.add(body, shape)
            
        return new_space, env, actual_index
        
    except Exception as e:
        print(f"Error loading map: {e}")
        return None, None, 0

space, cave_env, current_map_index = load_level(0)
if not space:
    pygame.quit()
    exit()

start_x, start_y = find_safe_start(cave_env, DISPLAY_WIDTH, DISPLAY_HEIGHT)
submarine = Submarine(start_x, start_y)

sonar_body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
sonar_body.position = (submarine.true_x, submarine.true_y)
space.add(sonar_body)

my_sonar = Sonar(space, sonar_body, num_rays=16, max_range=200, agent_size=30)

running = True
clock = pygame.time.Clock()

camera_x = 0
camera_y = 0

while running:
    clock.tick(60)
    for event in pygame.event.get():
        if event.type == QUIT:
            running = False

        if event.type == KEYDOWN:
            if submarine.battery > 0:
                if event.key == K_UP: submarine.move_up()
                elif event.key == K_DOWN: submarine.move_down()
                elif event.key == K_LEFT: submarine.move_left()
                elif event.key == K_RIGHT: submarine.move_right()
            
            new_space = None
            new_env = None
            new_idx = 0
            
            if event.key == K_1: new_space, new_env, new_idx = load_level(0)
            elif event.key == K_2: new_space, new_env, new_idx = load_level(1)
            elif event.key == K_3: new_space, new_env, new_idx = load_level(2)
            elif event.key == K_4: new_space, new_env, new_idx = load_level(3)
            elif event.key == K_5: new_space, new_env, new_idx = load_level(4)
            elif event.key == K_6: new_space, new_env, new_idx = load_level(5)
            elif event.key == K_7: new_space, new_env, new_idx = load_level(6)
            
            if new_space:
                space = new_space
                cave_env = new_env
                current_map_index = new_idx
                my_sonar.space = space
                
                sonar_body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
                sx, sy = find_safe_start(cave_env, DISPLAY_WIDTH, DISPLAY_HEIGHT)
                sonar_body.position = (sx, sy)
                space.add(sonar_body)
                my_sonar.body = sonar_body
                
                submarine.true_x, submarine.true_y = sx, sy
                submarine.battery = 100

    submarine.update()
    sonar_body.position = (submarine.rect.centerx, submarine.rect.centery)

    sensor_data = my_sonar.get_observation()
    hit_wall = False
    for reading in sensor_data:
        if reading == 0:
            hit_wall = True
            break
            
    if hit_wall:
        submarine.battery -= 10
        submarine.vel_x *= -0.5
        submarine.vel_y *= -0.5
        submarine.true_x += submarine.vel_x * 5
        submarine.true_y += submarine.vel_y * 5

    if submarine.battery < 0:
        submarine.battery = 0

    target_cam_x = submarine.true_x - DISPLAY_WIDTH / 2
    target_cam_y = submarine.true_y - DISPLAY_HEIGHT / 2
    camera_x += (target_cam_x - camera_x) * 0.1
    camera_y += (target_cam_y - camera_y) * 0.1
    
    canvas.fill((0, 128, 255))
    
    # manual blit for camera offset
    canvas.blit(cave_env.environment_surface, (cave_env.start_x - camera_x, cave_env.start_y - camera_y))
    
    screen_pos_x = submarine.rect.x - camera_x
    screen_pos_y = submarine.rect.y - camera_y
    canvas.blit(submarine.image, (screen_pos_x, screen_pos_y))
    
    # manual sonar draw for camera offset
    start_angle = sonar_body.angle
    step_angle = (2 * math.pi) / 16
    for i in range(16):
        distance = sensor_data[i] * 200 # MAX_RANGE
        local_angle = i * step_angle
        world_angle = start_angle + local_angle
        direction = pymunk.Vec2d(math.cos(world_angle), math.sin(world_angle))
        
        dist_to_edge = my_sonar._get_surface_offset(local_angle)
        world_start = sonar_body.position + direction * dist_to_edge
        world_end = world_start + direction * distance
        
        screen_start = (world_start.x - camera_x, world_start.y - camera_y)
        screen_end = (world_end.x - camera_x, world_end.y - camera_y)
        
        pygame.draw.line(canvas, (255, 255, 255), screen_start, screen_end, 1)
        
        if distance < 200:
             text = font.render(f"{int(distance)}", True, (200, 200, 200))
             canvas.blit(text, (screen_end[0] + 5, screen_end[1] + 5))

    battery_text = font.render(f'Battery: {submarine.battery} | Map: {map_files[current_map_index]}', True, (255, 255, 255))
    controls_text = font.render('Arrows: Move | 1-7: Change Map', True, (255, 255, 0))
    
    canvas.blit(battery_text, (10, 10))
    canvas.blit(controls_text, (10, 30))
    screen.blit(canvas, (0, 0))
    pygame.display.flip()
    clock.tick(60)

pygame.quit()
