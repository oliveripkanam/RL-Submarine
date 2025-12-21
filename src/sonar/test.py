import pygame
import pymunk
import math
import random
from src.sonar.sensors import Sonar

# CONFIG
WIDTH, HEIGHT = 800, 600
ENCLOSURE_SIZE = 250
AGENT_SIZE = 40
MOVE_SPEED = 4

def create_enclosure(space, shape_type):
    for shape in list(space.shapes):
        if hasattr(shape, "custom_type") and shape.custom_type == "wall":
            space.remove(shape)

    center = (WIDTH // 2, HEIGHT // 2)
    walls = []
    
    # radius 1.0 matches visual line thickness of 2
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

    # physics walls are slippery (friction 0) and hard (elasticity 0)
    # note: can change elasticity to make walls more or less bouncy
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

    sonar = Sonar(space, agent, num_rays=16, max_range=1000, agent_size=AGENT_SIZE)

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_1: 
                    create_enclosure(space, "SQUARE")
                    current_mode="SQUARE"
                    agent.position = (WIDTH // 2, HEIGHT // 2)
                elif event.key == pygame.K_2: 
                    create_enclosure(space, "CIRCLE")
                    current_mode="CIRCLE"
                    agent.position = (WIDTH // 2, HEIGHT // 2)
                elif event.key == pygame.K_3: 
                    create_enclosure(space, "IRREGULAR")
                    current_mode="IRREGULAR"
                    agent.position = (WIDTH // 2, HEIGHT // 2)

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

        # use the new sonar class
        sonar.draw(screen, font)
        
        info = font.render(f"Mode: {current_mode} | Move: WASD | 1,2,3: Change Shape", True, (255, 255, 0))
        screen.blit(info, (10, 10))

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()

if __name__ == "__main__":
    main()
