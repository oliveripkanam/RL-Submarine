import pygame
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import pymunk
import numpy as np
import glob
import random
import math
from src.cave_environment.environment import CaveEnvironment
from src.cave_environment.spritesheet import SpriteSheet
from src.entities.submarine import Submarine
from src.sonar.sensors import Sonar
from src.ai.agent import DoubleDQNAgent, VanillaDQNAgent

# Configuration
WATCH_MODE = False
<<<<<<< HEAD
LOAD_MODEL = False     # IMPORTANT: Set to "True" to continue training from previous save
NUM_EPISODES = 5000
=======
LOAD_MODEL = True     # IMPORTANT: Set to "True" to continue training from previous save
NUM_EPISODES = 10000
>>>>>>> ddqn-training-new-values
MAX_STEPS = 4000
BATCH_SIZE = 128
EPSILON_START = 0.1
EPSILON_END = 0.01
EPSILON_DECAY = 0.999
TARGET_UPDATE = 1000
SAVE_INTERVAL = 50

# Map configuration
MAP_FILES = [
    "src/cave_environment/map1_basic.csv",
    "src/cave_environment/map2_jagged.csv",
    "src/cave_environment/map3_jagged_long_narrow.csv",
    "src/cave_environment/map5_one_battery.csv",
    "src/cave_environment/map6_three_battery.csv",
    "src/cave_environment/map7_obstacle_simple.csv",
    "src/cave_environment/map8_obstacle_hard.csv",
]

# Initialize pygame
pygame.init()
screen = pygame.display.set_mode((1200, 800))
clock = pygame.time.Clock()
font = pygame.font.Font(None, 25)
hit_font = pygame.font.Font(None, 40)

def load_level(map_index, spritesheet):
    """Loads a specific map and initializes the physics space."""
    try:
        filename = MAP_FILES[map_index]
        env = CaveEnvironment(filename, spritesheet)
        
        new_space = pymunk.Space()
        new_space.gravity = (0, 0)
        
        for tile in env.environment_tiles:
            body = pymunk.Body(body_type=pymunk.Body.STATIC)
            body.position = (tile.rect.centerx, tile.rect.centery)
            shape = pymunk.Poly.create_box(body, (tile.rect.width, tile.rect.height))
            shape.filter = pymunk.ShapeFilter(group=1)
            new_space.add(body, shape)

        for obstacle in env.obstacles:
            body = pymunk.Body(body_type=pymunk.Body.STATIC)
            body.position = (obstacle.rect.centerx, obstacle.rect.centery)
            shape = pymunk.Poly.create_box(body, (obstacle.rect.width, obstacle.rect.height))
            shape.filter = pymunk.ShapeFilter(group=1)
            new_space.add(body, shape)
            
        return new_space, env
    except Exception as e:
        print(f"Error loading map {map_index}: {e}")
        return None, None

def get_full_state(sonar_data, submarine, map_idx, env_width, batteries):
    normalized_battery = submarine.battery / 500.0
    norm_vx = (submarine.vel_x + 10.0) / 20.0
    norm_vy = (submarine.vel_y + 10.0) / 20.0
    
    # Split-brain architecture (One-hot encoding)
    # We  tell the agent what type of map it is in using distinct neurons
    # Slot 0: Is_Straight (maps 0, 1)
    # Slot 1: Is_Narrow (map 2)
    # Slot 2: Is_Battery (maps 3, 4)
    # Slot 3: Is_Obstacle (maps 5, 6)
    is_straight = 1.0 if map_idx in [0, 1] else 0.0
    is_narrow = 1.0 if map_idx == 2 else 0.0
    is_battery = 1.0 if map_idx in [3, 4] else 0.0
    is_obstacle = 1.0 if map_idx in [5, 6] else 0.0
    
    map_encoding = [0.0] * 20
    map_encoding[0] = is_straight
    map_encoding[1] = is_narrow
    map_encoding[2] = is_battery
    map_encoding[3] = is_obstacle
    
    # Inject normalized X-position into the last slot of map_encoding
    map_encoding[-1] = submarine.true_x / env_width

    # Battery sensor
    closest_dist = float('inf')
    bat_dx = 0.0
    bat_dy = 0.0
    
    if batteries and len(batteries) > 0:
        sub_x, sub_y = submarine.rect.centerx, submarine.rect.centery
        for bat in batteries:
            dx = bat.rect.centerx - sub_x
            dy = bat.rect.centery - sub_y
            dist = dx*dx + dy*dy
            if dist < closest_dist:
                closest_dist = dist
                bat_dx = dx
                bat_dy = dy
        
        # Normalize (assuming max view distance approx 1000px)
        # We clamp it to -1.0 to 1.0 range
        map_encoding[17] = max(-1.0, min(1.0, bat_dx / 1000.0))
        map_encoding[18] = max(-1.0, min(1.0, bat_dy / 1000.0))
    
    return np.concatenate([
        sonar_data,
        [normalized_battery],
        [norm_vx, norm_vy],
        map_encoding
    ])

def train():
    global WATCH_MODE
    
    # Auto-cleanup: If starting fresh, delete old models
    if not LOAD_MODEL:
        files = glob.glob("models/*.pth")
        for f in files:
            try:
                os.remove(f)
            except Exception as e:
                print(f"Error deleting {f}: {e}")
        if files:
            print("Cleared previous models.")

    # Pre-load all maps
    spritesheet = SpriteSheet("src/cave_environment/tileset.png")
    print("Pre-loading maps...")
    preloaded_maps = []
    for i in range(len(MAP_FILES)):
        s, e = load_level(i, spritesheet)
        preloaded_maps.append((s, e))
    print("Maps loaded.")
    
    # Initialize agent
    # Actions: up, down, left, right, glide (do nothing)
    # Input shape: 16 sonar + 1 battery + 2 velocity + 20 map_id (for future support)= 39
    agent = VanillaDQNAgent(input_shape=39, num_actions=5)
    epsilon = EPSILON_START
    episode_loss = np.full(NUM_EPISODES, None, dtype=np.float32)

    total_steps = 0

    print(f"Starting training on Device: {agent.device}")
    print("Press TAB to toggle Fast/Watch Mode. Press ESC to quit.")

    # Success tracking
    success_history = []
    loss_history = []
    map_stats = {
        i: {'goals': 0, 'attempts': 0, 'total_reward': 0} 
        for i in range(len(MAP_FILES))
    }
    
    # Battery stats tracking
    battery_stats = {
        i: {
            'picked_up': 0,      # Total runs where at least 1 battery was grabbed
            'picked_success': 0, # Grabbed battery AND reached goal
            'picked_fail': 0,    # Grabbed battery BUT died
            'ignored_fail': 0,   # Ignored battery AND died
            'ignored_success': 0 # Ignored battery AND reached goal
        }
        for i in range(len(MAP_FILES))
    }
    
    # Obstacle stats tracking
    obstacle_stats = {
        i: {
            'avoided_won': 0,
            'avoided_died': 0,
            'hit_died': 0,
            'hit_won': 0
        }
        for i in range(len(MAP_FILES))
    }

    # Clean run stats tracking
    clean_stats = {
        i: {
            'clean_win': 0,
            'dirty_win': 0,
            'clean_fail': 0,
            'dirty_fail': 0
        }
        for i in range(len(MAP_FILES))
    }

    start_episode = 0

    if LOAD_MODEL:
        model_path = "models/vanilla_dqn_submarine_final.pth"
        if not os.path.exists(model_path):
            # Try to find the latest checkpoint
            list_of_files = glob.glob('models/vanilla_dqn_submarine_ep*.pth')
            if list_of_files:
                model_path = max(list_of_files, key=os.path.getctime)
                # Try to extract episode number
                try:
                    start_episode = int(model_path.split("ep")[-1].split(".")[0])
                    print(f"Found checkpoint: {model_path} (Episode {start_episode})")
                except:
                    pass
        
        try:
            agent.load(model_path)
            print(f"Successfully loaded model: {model_path}")
            epsilon = EPSILON_START
        except Exception as e:
            print(f"Could not load model ({e}). Starting fresh!")
            epsilon = 1.0 # Reset exploration for new brain
    
    for episode in range(start_episode, NUM_EPISODES):

        # Weighted training
        rand_val = random.random()
        if rand_val < 0.5:
            map_idx = 6            
        elif rand_val < 0.8:
            map_idx = 2             
        elif rand_val < 0.9:
            map_idx = 4             
        else:
            map_idx = random.choice([0, 1, 3, 5])
            
        map_stats[map_idx]['attempts'] += 1
        
        # Load environment & physics from cache
        space, cave_env = preloaded_maps[map_idx]
        
        # Clear and re-parse dynamic entities
        cave_env.batteries.empty()
        cave_env.obstacles.empty()
        
        # Parse map data again for dynamic entities
        with open(MAP_FILES[map_idx], 'r') as f:
            data = f.readlines()
            for y, line in enumerate(data):
                row = line.strip().split(',')
                for x, tile in enumerate(row):
                    if tile == '20': # Battery
                        from src.entities.items import Battery
                        cave_env.batteries.add(Battery(x * 16, y * 16))
                    elif tile == '21': # Obstacle
                        from src.entities.items import Obstacle
                        cave_env.obstacles.add(Obstacle(x * 16, y * 16))

        # Clean up previous dynamic bodies
        for body in space.bodies:
            if body.body_type == pymunk.Body.KINEMATIC or body.body_type == pymunk.Body.DYNAMIC:
                space.remove(body)
                for shape in body.shapes:
                    space.remove(shape)
        
        if not space:
            continue

        # Reset sub
        start_x, start_y = 100, 300
        
        # Always start from the left (Deep End strategy)
        target_x_min = 50
        
        # safe start logic
        found_start = False
        wall_rects = [t.rect for t in cave_env.environment_tiles]
        
        # Search forward
        for x in range(target_x_min, cave_env.environment_width - 50, 20):
             valid_ys = []
             search_y_start = 50
             search_y_end = cave_env.environment_height - 50
             
             for y in range(search_y_start, search_y_end, 10):
                 # Check with a 60x60 margin to fit in tight obstacle maps
                 test_rect = pygame.Rect(x - 30, y - 30, 60, 60)
                 if test_rect.collidelist(wall_rects) == -1:
                     valid_ys.append(y)
             
             if len(valid_ys) > 0:
                 start_x = x
                 start_y = sum(valid_ys) // len(valid_ys)
                 found_start = True
                 break
        
        # Search backward (if forward failed)
        if not found_start:
            for x in range(target_x_min, 100, -20):
                 valid_ys = []
                 search_y_start = 50
                 search_y_end = cave_env.environment_height - 50
                 
                 for y in range(search_y_start, search_y_end, 10):
                     test_rect = pygame.Rect(x - 30, y - 30, 60, 60)
                     if test_rect.collidelist(wall_rects) == -1:
                         valid_ys.append(y)
                 
                 if len(valid_ys) > 0:
                     start_x = x
                     start_y = sum(valid_ys) // len(valid_ys)
                     found_start = True
                     break
        
        if not found_start:
            # If no safe spot, default to start of map which is always safe.
            start_x, start_y = 100, 300
            print(f"WARNING: Could not find safe spawn at x={target_x_min}. Resetting to start.")
            
        submarine = Submarine(start_x, start_y)
        
        # Custom difficulty, less battery for map 5 & 6
        if map_idx in [3, 4]:
            submarine.battery = 300
        else:
            submarine.battery = 600
            
        current_run_picked_battery = False
        hit_obstacle_this_run = False
        hit_wall_this_run = False
        
        sonar_body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
        sonar_body.position = (submarine.rect.centerx, submarine.rect.centery)
        sonar = Sonar(space, sonar_body)
        
        state = get_full_state(sonar.get_observation(), submarine, map_idx, cave_env.environment_width, cave_env.batteries)
        total_reward = 0
        done = False
        
        # Stagnation check variables
        stagnation_start_x = submarine.true_x
        stagnation_timer = 0
        
        action = 4

        for step in range(MAX_STEPS):
            # Event handling
            if WATCH_MODE:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        pygame.quit()
                        return
                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            pygame.quit()
                            return
                        if event.key == pygame.K_TAB:
                            WATCH_MODE = not WATCH_MODE
                            print(f"Watch Mode: {WATCH_MODE}")
            if step % 10 == 0: # Check every 10 steps in Fast Mode
                 for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        pygame.quit()
                        return
                    if event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            pygame.quit()
                            return
                        if event.key == pygame.K_TAB:
                            WATCH_MODE = not WATCH_MODE
                            print(f"Watch Mode: {WATCH_MODE}")

            # Dynamic epsilon
            current_epsilon = epsilon

            if step % 4 == 0:
                action = agent.select_action(state, current_epsilon)
            
            # Save previous position
            prev_x = submarine.true_x
            prev_y = submarine.true_y
            
            # Battery homing reward before moving
            # DISABLED FOR PPO MATCHING
            # prev_bat_dist = float('inf')
            # if map_idx in [3, 4] and len(cave_env.batteries) > 0:
            #     for bat in cave_env.batteries:
            #         d = math.hypot(bat.rect.centerx - submarine.rect.centerx, bat.rect.centery - submarine.rect.centery)
            #         if d < prev_bat_dist: prev_bat_dist = d
            
            reward = 0.0 # Base penalty (Time Penalty = 0)

            if action == 0: # Up
                submarine.move_up()
            elif action == 1: # Down
                submarine.move_down()
            elif action == 2: # Left
                submarine.move_left()
            elif action == 3: # Right
                submarine.move_right()
            elif action == 4: # Glide
                # do nothing
                reward += 0.05 # Efficiency bonus
                pass
            
            submarine.update()
            sonar_body.position = (submarine.rect.centerx, submarine.rect.centery)
            
            # Battery homing reward after moving
            # DISABLED FOR PPO MATCHING
            # curr_bat_dist = float('inf')
            # if map_idx in [3, 4] and len(cave_env.batteries) > 0:
            #     for bat in cave_env.batteries:
            #         d = math.hypot(bat.rect.centerx - submarine.rect.centerx, bat.rect.centery - submarine.rect.centery)
            #         if d < curr_bat_dist: curr_bat_dist = d
            
            # Apply homing reward
            battery_picked_up_this_frame = False
            
            # Distance-based reward
            dist_x = submarine.true_x - prev_x
            
            # Base distance reward (Forward Drive = +0.5, clipped)
            dist_reward = max(-1.0, min(2.0, dist_x * 0.5))
            
            # Initialize variables
            speed_penalty = 0.0
            safety_reward = 0.0
            loitering_penalty = 0.0
            
            # Get sonar for safety calculations
            current_observation = sonar.get_observation()
            min_wall_dist = min(current_observation)

            # Survival maps
            if map_idx in [2, 5, 6]:
                
                # Speed penalty (Drag = 0)
                speed_penalty = 0.0
                
                # Safety cushion (Safety Cushion = 0)
                safety_reward = 0.0
                
                # Loitering penalty (Loitering = 0)
                loitering_penalty = 0.0

            # Hunting maps
            elif map_idx == 4 or map_idx == 3:
                # No speed penalty
                speed_penalty = 0.0
                
                # Always-on safety cushion (No velocity gate)
                # We want it to be safe even if it slows down to aim
                safety_reward = 0.0
                
                # Hunting bonus 
                # Reward vertical movement to encourage looking for batteries
                # DISABLED FOR PPO MATCHING
                # if abs(submarine.vel_y) > 0.5:
                #     reward += 0.5

                # Urgency bonus
                # If battery is high (> 400), encourage moving RIGHT to finish
                # DISABLED FOR PPO MATCHING
                # if submarine.battery > 400:
                #     reward += dist_x * 2.0
            
            # Final sum
            reward += dist_reward - speed_penalty + safety_reward + loitering_penalty
            
            # Cowardice penalty
            # DISABLED FOR PPO MATCHING (Handled by clipping above)
            # if dist_x < -0.5:
            #     reward -= 0.5

            # Time penalty (Time Penalty = 0)
            # reward -= 0.01
            # Check for battery pickups
            hits = pygame.sprite.spritecollide(submarine, cave_env.batteries, True)
            for hit in hits:
                submarine.battery += 300
                reward += 10.0 # Battery = +10
                current_run_picked_battery = True
                battery_picked_up_this_frame = True

            # Check for obstacle collisions (Pufferfish)
            obs_hits = pygame.sprite.spritecollide(submarine, cave_env.obstacles, True)
            for hit in obs_hits:
                submarine.battery -= 50
                reward -= 5.0 # Obstacle Hit = -5.0
                hit_obstacle_this_run = True
            
            # Apply homing reward
            # DISABLED FOR PPO MATCHING
            # if map_idx in [3, 4] and not battery_picked_up_this_frame:
            #     if prev_bat_dist != float('inf') and curr_bat_dist != float('inf'):
            #         diff = prev_bat_dist - curr_bat_dist
            #         # If diff is positive = we got closer, reward it
            #         # If diff is negative = we moved away, penalize it
            #         reward += diff * 4.0 
            
            # We already called sonar.get_observation() earlier for the safety reward
            # Reuse it here to avoid double computation
            next_observation = current_observation 
            next_state = get_full_state(next_observation, submarine, map_idx, cave_env.environment_width, cave_env.batteries)

            # Store experience in replay buffer
            agent.memory.push(state, action, reward, next_state, done)
            
            # Accumulate reward
            total_reward += reward

            display_hit_msg = False
            
            hit_wall = False
            for reading in next_observation:
                if reading == 0: 
                    hit_wall = True
                    break
            
            if hit_wall:
                hit_wall_this_run = True
                # Hitting a wall at high speed is bad
                current_speed = math.sqrt(submarine.vel_x**2 + submarine.vel_y**2)
                
                # Wall Collision = -50 (Uniform)
                penalty = 50.0
                
                reward -= penalty
                
                submarine.battery -= 10
                display_hit_msg = True
                
                # Hard revert: restore position to before the collision
                submarine.true_x = prev_x
                submarine.true_y = prev_y
                submarine.rect.x = int(prev_x)
                submarine.rect.y = int(prev_y)
                
                # Apply recoil velocity
                submarine.vel_x *= -0.5
                submarine.vel_y *= -0.5
                
                # Update physics body immediately
            if submarine.rect.right >= cave_env.environment_width - 10:
                # Goal Reached = +100
                reward += 100.0
                
                # Survival bonus for maps with no batteries (Goal Reached +50 if all batteries collected logic)
                # Since we don't track "all collected", we use the "no batteries on map" logic as a proxy or just add it
                if len(cave_env.batteries) == 0:
                    reward += 50.0
                
                reward += submarine.battery * 1.0 # Battery Residual (assuming 1:1 ratio based on "battery residual")
                done = True
                success_history.append(1)
                map_stats[map_idx]['goals'] += 1

            if submarine.battery <= 0:
                reward -= 10.0 # Death = -10
                done = True
                success_history.append(0)
            # Stagnation check
            stagnation_timer += 1
            if stagnation_timer >= 300:
                if abs(submarine.true_x - stagnation_start_x) < 100:
                    reward -= 5.0 # Stagnation = -5
                    done = True
                    success_history.append(0)
                    # Reset timer and position if moved enough
                    stagnation_timer = 0
                    stagnation_start_x = submarine.true_x

            if step % 4 == 0:
                loss = agent.train_step(BATCH_SIZE)
                if loss is not None:
                    loss_history.append(loss)
            
            total_steps += 1
            if total_steps % TARGET_UPDATE == 0:
                agent.update_target_network()

            state = next_state

            if WATCH_MODE:
                canvas = pygame.Surface((cave_env.environment_width, cave_env.environment_height))
                canvas.fill((0, 128, 255))
                cave_env.draw(canvas)
                submarine.draw(canvas)
                sonar.draw(canvas, font)
                
                scale = min(1200 / cave_env.environment_width, 800 / cave_env.environment_height)
                new_size = (int(cave_env.environment_width * scale), int(cave_env.environment_height * scale))
                scaled = pygame.transform.smoothscale(canvas, new_size)
                
                screen.fill((0, 0, 0))
                screen.blit(scaled, ((1200 - new_size[0]) // 2, (800 - new_size[1]) // 2))
                
                # Info text
                info_text = f"Ep: {episode} | Step: {step} | Reward: {total_reward:.1f} | Eps: {epsilon:.2f}"
                batt_text = f"Battery: {submarine.battery:.1f}%"
                mode_text = "Press TAB for FAST MODE"
                
                screen.blit(font.render(info_text, True, (255, 255, 255)), (10, 10))
                screen.blit(font.render(batt_text, True, (255, 255, 0)), (10, 40))
                screen.blit(font.render(mode_text, True, (0, 255, 0)), (10, 70))

                if display_hit_msg:
                    hit_surf = hit_font.render("HIT WALL!", True, (255, 0, 0))
                    screen.blit(hit_surf, (1200 - 200, 50))
                
                pygame.display.flip()
                clock.tick(60)
            else:
                # In fast mode, pump events to keep window responsive but don't draw
                if step % 100 == 0:
                    screen.fill((0, 0, 0))
                    msg = font.render(f"FAST MODE (Ep {episode}). Press TAB to Watch.", True, (0, 255, 0))
                    screen.blit(msg, (1200//2 - 150, 800//2))
                    pygame.display.flip()

            if done:
                break
        map_stats[map_idx]['total_reward'] += total_reward
        
        # Update battery stats
        is_success = success_history[-1] == 1
        if current_run_picked_battery:
            battery_stats[map_idx]['picked_up'] += 1
            if is_success:
                battery_stats[map_idx]['picked_success'] += 1
            else:
                battery_stats[map_idx]['picked_fail'] += 1
        else:
            if is_success:
                battery_stats[map_idx]['ignored_success'] += 1
            else:
                battery_stats[map_idx]['ignored_fail'] += 1
        
        # Update obstacle stats
        if hit_obstacle_this_run:
            if is_success:
                obstacle_stats[map_idx]['hit_won'] += 1
            else:
                obstacle_stats[map_idx]['hit_died'] += 1
        else:
            if is_success:
                obstacle_stats[map_idx]['avoided_won'] += 1
            else:
                obstacle_stats[map_idx]['avoided_died'] += 1

        # Update clean run stats
        is_clean = not hit_wall_this_run and not hit_obstacle_this_run
        if is_clean:
            if is_success:
                clean_stats[map_idx]['clean_win'] += 1
            else:
                clean_stats[map_idx]['clean_fail'] += 1
        else:
            if is_success:
                clean_stats[map_idx]['dirty_win'] += 1
            else:
                clean_stats[map_idx]['dirty_fail'] += 1

        epsilon = max(EPSILON_END, epsilon * EPSILON_DECAY)
        #average_loss = total_loss / (step + 1)
        #episode_loss[episode] = average_loss
        if episode % 10 == 0:
            print(f"Episode {episode}/{NUM_EPISODES} | Total Reward: {total_reward:.2f} | Epsilon: {epsilon:.2f}")

        if episode % SAVE_INTERVAL == 0:
            agent.save(f"models/vanilla_dqn_submarine_ep{episode}.pth")
        

    np.save("models/vanilla_dqn_training_loss.npy", episode_loss)
    agent.save("models/vanilla_dqn_submarine_final.pth")
    
    print("\n" + "="*50)
    print("TRAINING COMPLETE - FINAL STATISTICS")
    print("="*50)
    print(f"{'Map File':<40} | {'Goals':<5} | {'Attempts':<8} | {'Success Rate':<12} | {'Avg Reward':<10}")
    print("-" * 85)
    
    for i, filename in enumerate(MAP_FILES):
        stats = map_stats[i]
        attempts = stats['attempts']
        goals = stats['goals']
        avg_reward = stats['total_reward'] / attempts if attempts > 0 else 0
        success_rate = (goals / attempts * 100) if attempts > 0 else 0
        
        display_name = filename.split('/')[-1]
        print(f"{display_name:<40} | {goals:<5} | {attempts:<8} | {success_rate:<11.1f}% | {avg_reward:<10.1f}")
    print("="*50)

    print("\n" + "="*50)
    print("BATTERY STATS")
    print("="*50)
    print(f"{'Map File':<25} | {'Picked(Up)':<11} | {'Picked(Win)':<11} | {'Picked(Die)':<11} | {'Ignored(Die)':<12} | {'Ignored(Win)':<12}")
    print("-" * 90)

    for i, filename in enumerate(MAP_FILES):
        # Show battery stats for map 5 and 6
        if i in [3, 4] and i in battery_stats and map_stats[i]['attempts'] > 0:
            bs = battery_stats[i]
            display_name = filename.split('/')[-1]
            print(f"{display_name:<25} | {bs['picked_up']:<11} | {bs['picked_success']:<11} | {bs['picked_fail']:<11} | {bs['ignored_fail']:<12} | {bs['ignored_success']:<12}")
    print("="*50)

    print("\n" + "="*50)
    print("OBSTACLE STATS")
    print("="*50)
    print(f"{'Map File':<25} | {'Avoid(Win)':<11} | {'Avoid(Die)':<11} | {'Hit(Die)':<11} | {'Hit(Win)':<11}")
    print("-" * 90)

    for i, filename in enumerate(MAP_FILES):
        # Show obstacle stats for map 7 and 8
        if i in [5, 6] and i in obstacle_stats and map_stats[i]['attempts'] > 0:
            os_stats = obstacle_stats[i]
            display_name = filename.split('/')[-1]
            print(f"{display_name:<25} | {os_stats['avoided_won']:<11} | {os_stats['avoided_died']:<11} | {os_stats['hit_died']:<11} | {os_stats['hit_won']:<11}")
    print("="*50)

    print("\n" + "="*50)
    print("CLEAN RUN STATS (No Wall/Obstacle Hits)")
    print("="*50)
    print(f"{'Map File':<25} | {'Clean Win':<11} | {'Dirty Win':<11} | {'Clean Fail':<11} | {'Dirty Fail':<11}")
    print("-" * 90)

    for i, filename in enumerate(MAP_FILES):
        if map_stats[i]['attempts'] > 0:
            cs = clean_stats[i]
            display_name = filename.split('/')[-1]
            print(f"{display_name:<25} | {cs['clean_win']:<11} | {cs['dirty_win']:<11} | {cs['clean_fail']:<11} | {cs['dirty_fail']:<11}")
    print("="*50)
    
    # Save loss data
    np.save("training_loss.npy", np.array(loss_history))
    print("Network Training Loss saved to 'training_loss.npy'")
    
    avg_first_100 = sum(loss_history[:100]) / len(loss_history[:100]) if len(loss_history) >= 100 else 0
    avg_last_100 = sum(loss_history[-100:]) / len(loss_history[-100:]) if len(loss_history) >= 100 else 0
    peak_loss = max(loss_history) if loss_history else 0
    
    print("\n" + "="*50)
    print("NETWORK HEALTH & LOSS")
    print("="*50)
    print(f"Avg Loss (First 100 Eps):  {avg_first_100:.3f}")
    print(f"Avg Loss (Last 100 Eps):   {avg_last_100:.3f}")
    print(f"Peak Loss:                 {peak_loss:.3f}")
    print(f"Total Training Steps:      {total_steps}")
    print("="*50)

    pygame.quit()

if __name__ == "__main__":
    train()
