import pygame
import pymunk
import math
import random
import numpy as np

# CONFIG
WIDTH, HEIGHT = 800, 600
NUM_RAYS = 16
MAX_RANGE = 1000
ENCLOSURE_SIZE = 250
AGENT_SIZE = 40
MOVE_SPEED = 4

def create_enclosure(space, shape_type):
    for shape in list(space.shapes):
        if hasattr(shape, "custom_type") and shape.custom_type == "wall":
            space.remove(shape)

    center = (WIDTH // 2, HEIGHT // 2)
    walls = []
    wall_thickness = 1.0 

    if shape_type == "SQUARE":
        w, h = ENCLOSURE_SIZE * 2, ENCLOSURE_SIZE * 2
        tl, tr = (center[0] - w/2, center[1] - h/2), (center[0] + w/2, center[1] - h/2)
        br, bl = (center[0] + w/2, center[1] + h/2), (center[0] - w/2, center[1] + h/2)
        walls = [
            pymunk.Segment(space.static_body, tl, tr, wall_thickness),
            pymunk.Segment(space.static_body, tr, br, wall_thickness),
            pymunk.Segment(space.static_body, br, bl, wall_thickness),
            pymunk.Segment(space.static_body, bl, tl, wall_thickness)
        ]

    elif shape_type == "CIRCLE":
        steps = 64
        vertices = []
        for i in range(steps):
            angle = math.radians(i * (360 / steps))
            x = center[0] + ENCLOSURE_SIZE * math.cos(angle)
            y = center[1] + ENCLOSURE_SIZE * math.sin(angle)
            vertices.append((x, y))
        for i in range(len(vertices)):
            walls.append(pymunk.Segment(space.static_body, vertices[i], vertices[(i + 1) % len(vertices)], wall_thickness))

    elif shape_type == "IRREGULAR":
        steps = 12
        vertices = []
        for i in range(steps):
            angle = math.radians(i * (360 / steps))
            r = ENCLOSURE_SIZE * random.uniform(0.5, 1.2)
            x = center[0] + r * math.cos(angle)
            y = center[1] + r * math.sin(angle)
            vertices.append((x, y))
        for i in range(len(vertices)):
            walls.append(pymunk.Segment(space.static_body, vertices[i], vertices[(i + 1) % len(vertices)], wall_thickness))

    for wall in walls:
        wall.elasticity = 0.0
        wall.friction = 0.0
        wall.custom_type = "wall"
        space.add(wall)

def create_agent(space):
    # Kinematic body allows manual movement control (WASD)
    body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
    body.position = (WIDTH // 2, HEIGHT // 2)
    body.angle = 0 

    shape = pymunk.Poly.create_box(body, (AGENT_SIZE, AGENT_SIZE))
    shape.filter = pymunk.ShapeFilter(group=1) # group 1 ignores self-collisions
    space.add(body, shape)
    return body

def get_surface_offset(angle_rad, size):
    # finds distance from center to the edge of the square at a given angle
    angle_rad = (angle_rad + math.pi) % (2 * math.pi) - math.pi
    half_size = size / 2
    cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)
    if abs(cos_a) < 0.0001: cos_a = 0.0001
    if abs(sin_a) < 0.0001: sin_a = 0.0001
    return half_size / max(abs(cos_a), abs(sin_a))

def get_sensor_data(space, body):
    # Returns a numpy array of normalized distances (0.0 to 1.0)
    start_angle = body.angle
    step_angle = (2 * math.pi) / NUM_RAYS
    readings = []

    for i in range(NUM_RAYS):
        local_angle = i * step_angle
        world_angle = start_angle + local_angle
        direction = pymunk.Vec2d(math.cos(world_angle), math.sin(world_angle))
        
        # Get distance to the border
        dist_to_edge = get_surface_offset(local_angle, AGENT_SIZE)
        
        # Start ray deeper inside (10px) to catch wall penetrations (else it'll pass through the wall)
        start_pos = body.position + direction * (dist_to_edge - 10)
        end_pos = start_pos + direction * MAX_RANGE
        
        result = space.segment_query_first(start_pos, end_pos, 1, pymunk.ShapeFilter(group=1))
        
        visual_start_pos = body.position + direction * dist_to_edge
        actual_end = result.point if result else end_pos
        
        # Calculate raw distance
        raw_dist = visual_start_pos.get_distance(actual_end) if result else MAX_RANGE
        
        # Check for wall clipping
        dist_center_to_hit = body.position.get_distance(actual_end) if result else 9999
        dist_center_to_border = dist_to_edge
        
        distance = raw_dist
        if result and dist_center_to_hit < dist_center_to_border:
             distance = 0

        # Snap small gaps to 0
        if distance < 2.0:
            distance = 0

        # Normalize to 0.0 - 1.0
        readings.append(distance / MAX_RANGE)

    return np.array(readings)

def draw_sensor_debug(surface, body, data, font):
    # Draws the rays based on the calculated data
    start_angle = body.angle
    step_angle = (2 * math.pi) / NUM_RAYS
    hit_wall = False

    for i in range(NUM_RAYS):
        distance = data[i] * MAX_RANGE
        if distance == 0:
            hit_wall = True
            
        local_angle = i * step_angle
        world_angle = start_angle + local_angle
        direction = pymunk.Vec2d(math.cos(world_angle), math.sin(world_angle))
        dist_to_edge = get_surface_offset(local_angle, AGENT_SIZE)
        
        visual_start_pos = body.position + direction * dist_to_edge
        actual_end = visual_start_pos + direction * distance
        
        pygame.draw.line(surface, (255, 255, 255), visual_start_pos, actual_end, 1)
        
        if distance < MAX_RANGE:
            text = font.render(f"{int(distance)}", True, (200, 200, 200))
            surface.blit(text, actual_end + (5, 5))

    if hit_wall:
        msg = font.render("HIT A WALL!", True, (255, 50, 50))
        surface.blit(msg, (WIDTH - 120, 10))

def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Sonar Test")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("Arial", 12)

    space = pymunk.Space()
    current_mode = "SQUARE"
    create_enclosure(space, current_mode)
    agent = create_agent(space)

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_1: create_enclosure(space, "SQUARE"); current_mode="SQUARE"
                elif event.key == pygame.K_2: create_enclosure(space, "CIRCLE"); current_mode="CIRCLE"
                elif event.key == pygame.K_3: create_enclosure(space, "IRREGULAR"); current_mode="IRREGULAR"

        keys = pygame.key.get_pressed()
        
        move_vec = pymunk.Vec2d(0, 0)
        if keys[pygame.K_w]: move_vec += (0, -MOVE_SPEED)
        if keys[pygame.K_s]: move_vec += (0, MOVE_SPEED)
        if keys[pygame.K_a]: move_vec += (-MOVE_SPEED, 0)
        if keys[pygame.K_d]: move_vec += (MOVE_SPEED, 0)
        
        if move_vec.length > 0:
            proposed_pos = agent.position + move_vec
            
            # ghost check: place a dummy box at target pos to see if it overlaps anything
            dummy_body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
            dummy_body.position = proposed_pos
            dummy_body.angle = agent.angle
            dummy_shape = pymunk.Poly.create_box(dummy_body, (AGENT_SIZE, AGENT_SIZE))
            
            matches = space.shape_query(dummy_shape)
            
            is_blocked = False
            for match in matches:
                # check if we hit a wall (ignore self)
                if match.shape != list(agent.shapes)[0] and match.shape in space.shapes:
                    if match.contact_point_set.points:
                        is_blocked = True
                        break
            
            if not is_blocked:
                agent.position = proposed_pos

        space.step(1 / 60.0)
        screen.fill((20, 20, 20))

        for shape in space.shapes:
            if hasattr(shape, "custom_type") and shape.custom_type == "wall":
                pygame.draw.line(screen, (200, 200, 200), shape.a, shape.b, 2)

        poly = list(agent.shapes)[0]
        v_world = [agent.local_to_world(v) for v in poly.get_vertices()]
        pygame.draw.polygon(screen, (50, 100, 255), v_world)

        # Get data (Physics only)
        sensor_data = get_sensor_data(space, agent)
        
        # Draw (Visuals only)
        draw_sensor_debug(screen, agent, sensor_data, font)
        
        info = font.render(f"Mode: {current_mode} | Move: WASD", True, (255, 255, 0))
        screen.blit(info, (10, 10))

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()

if __name__ == "__main__":
    main()
