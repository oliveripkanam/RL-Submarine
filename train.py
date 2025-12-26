import pygame
import pymunk
import numpy as np
import os
import glob
import random
from src.cave_environment.environment import CaveEnvironment
from src.cave_environment.spritesheet import SpriteSheet
from src.entities.submarine import Submarine
from src.sonar.sensors import Sonar
from src.ai.agent import DoubleDQNAgent

# Configuration
WATCH_MODE = False
LOAD_MODEL = True     # IMPORTANT: Set to "True" to continue training from previous save
NUM_EPISODES = 2000
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

def get_full_state(sonar_data, submarine, map_idx):
    normalized_battery = submarine.battery / 500.0
    norm_vx = (submarine.vel_x + 10.0) / 20.0
    norm_vy = (submarine.vel_y + 10.0) / 20.0
    
    map_encoding = [0.0] * 20
    if map_idx < 20:
        map_encoding[map_idx] = 1.0
    
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
    agent = DoubleDQNAgent(input_shape=39, num_actions=5)
    epsilon = EPSILON_START
    
    if LOAD_MODEL:
        try:
            agent.load("models/ddqn_submarine_final.pth")
            print("Successfully loaded existing model!")
            epsilon = 0.3
        except Exception as e:
            print(f"Could not load model ({e}). This is expected if you upgraded the Network Architecture (Bigger Brain). Starting fresh!")
            epsilon = 1.0 # Reset exploration for new brain


    total_steps = 0

    print(f"Starting training on Device: {agent.device}")
    print("Press TAB to toggle Fast/Watch Mode. Press ESC to quit.")

    # Success tracking
    success_history = []
    loss_history = []
    map1_history = []
    map2_history = []
    map3_history = []
    map_stats = {
        i: {'goals': 0, 'attempts': 0, 'total_reward': 0} 
        for i in range(len(MAP_FILES))
    }
    
    start_episode = 0
    
    # Load training state if exists and we are loading model
    if LOAD_MODEL and os.path.exists("training_state.npy"):
        try:
            state_data = np.load("training_state.npy", allow_pickle=True).item()
            map1_history = state_data.get('map1_history', [])
            map2_history = state_data.get('map2_history', [])
            map3_history = state_data.get('map3_history', [])
            print(f"Loaded training state. Histories - M1:{len(map1_history)} M2:{len(map2_history)} M3:{len(map3_history)}")
        except Exception as e:
            print(f"Error loading training state: {e}")

    for episode in range(start_episode, NUM_EPISODES):

        # Calculate sr
        recent_map1 = map1_history[-50:]
        map1_sr = sum(recent_map1) / len(recent_map1) if recent_map1 else 0.0

        recent_map2 = map2_history[-50:]
        map2_sr = sum(recent_map2) / len(recent_map2) if recent_map2 else 0.0
        
        recent_map3 = map3_history[-50:]
        map3_sr = sum(recent_map3) / len(recent_map3) if recent_map3 else 0.0
        
        # WEIGHTINGS
        map_idx = random.choices([0, 1, 2], weights=[10, 10, 80], k=1)[0]
        map_stats[map_idx]['attempts'] += 1
        
        # Load environment & physics from cache
        space, cave_env = preloaded_maps[map_idx]
        
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
        
        # below's for map 3 so it learns faster
        target_x_min = 50
        
        if map_idx == 2: # Map 3
            # Reverse curriculum
            if map3_sr > 0.8:
                target_x_min = 100
            elif map3_sr > 0.7:
                target_x_min = 500
            elif map3_sr > 0.6:
                target_x_min = 900
            elif map3_sr > 0.5:
                target_x_min = 1300
            elif map3_sr > 0.4:
                target_x_min = 1700
            elif map3_sr > 0.3:
                target_x_min = 2000
            elif map3_sr > 0.2:
                target_x_min = 2200
            else:
                target_x_min = 2500

            # Add variance to prevent overfitting to exact pixels
            target_x_min += random.randint(-50, 50)
            target_x_min = max(50, min(target_x_min, 2800))
            
        # safe start logic
        wall_rects = [t.rect for t in cave_env.environment_tiles]
        wall_rects.extend([o.rect for o in cave_env.obstacles])
        found_start = False
        
        for x in range(target_x_min, cave_env.environment_width - 50, 20):
             valid_ys = []
             search_y_start = 50
             search_y_end = cave_env.environment_height - 50
             
             for y in range(search_y_start, search_y_end, 10):
                 # Check with a 60x60 margin (sub is approx 40x40) to ensure air gap
                 test_rect = pygame.Rect(x - 30, y - 30, 60, 60)
                 if test_rect.collidelist(wall_rects) == -1:
                     valid_ys.append(y)
             
             if len(valid_ys) > 0:
                 start_x = x
                 start_y = sum(valid_ys) // len(valid_ys)
                 found_start = True
                 break
        
        if not found_start:
            if map_idx == 2:
                start_x, start_y = target_x_min, 300
        submarine = Submarine(start_x, start_y)
        
        sonar_body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
        sonar_body.position = (submarine.rect.centerx, submarine.rect.centery)
        sonar = Sonar(space, sonar_body)
        
        state = get_full_state(sonar.get_observation(), submarine, map_idx)
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
            elif step % 10 == 0: # Check every 10 steps in Fast Mode
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

            if step % 4 == 0:
                action = agent.select_action(state, epsilon)
            
            # Save previous position
            prev_x = submarine.true_x
            prev_y = submarine.true_y
            
            reward = -0.1 # Base penalty

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
            
            # Distance-based reward
            dist_x = submarine.true_x - prev_x
            
            # Context-aware grading
            reward += dist_x * 2.5
            
            # Cowardice penalty (Only for speed maps)
            if dist_x < -0.5:
                reward -= 0.5

            # Time penalty
            reward -= 0.01
            # Check for battery pickups
            hits = pygame.sprite.spritecollide(submarine, cave_env.batteries, True)
            for hit in hits:
                submarine.battery += 20
                reward += 2.0
            
            next_observation = sonar.get_observation()
            next_state = get_full_state(next_observation, submarine, map_idx)

            display_hit_msg = False
            
            hit_wall = False
            for reading in next_observation:
                if reading == 0: 
                    hit_wall = True
                    break
            
            if hit_wall:
                # Context-aware grading
                penalty = 2
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
                reward += 1000
                reward += submarine.battery * 0.1 # Bonus for efficiency
                done = True
                success_history.append(1)
                if map_idx == 0: map1_history.append(1)
                if map_idx == 1: map2_history.append(1)
                if map_idx == 2: map3_history.append(1)
                map_stats[map_idx]['goals'] += 1

            if submarine.battery <= 0:
                reward -= 10
                done = True
                success_history.append(0)
                if map_idx == 0: map1_history.append(0)
                if map_idx == 1: map2_history.append(0)
                if map_idx == 2: map3_history.append(0)
            
            # Stagnation check
            stagnation_timer += 1
            if stagnation_timer >= 300:
                if abs(submarine.true_x - stagnation_start_x) < 100:
                    reward -= 5.0 # Penalty for laziness
                    done = True
                    success_history.append(0)
                    if map_idx == 0: map1_history.append(0)
                    if map_idx == 1: map2_history.append(0)
                    if map_idx == 2: map3_history.append(0)
                else:
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
                if step % 1000 == 0:
                    screen.fill((0, 0, 0))
                    msg = font.render(f"FAST MODE (Ep {episode}). Press TAB to Watch.", True, (0, 255, 0))
                    screen.blit(msg, (1200//2 - 150, 800//2))
                    pygame.display.flip()

            if done:
                break
        
        # Cleanup physics body for next episode
        map_stats[map_idx]['total_reward'] += total_reward
        
        epsilon = max(EPSILON_END, epsilon * EPSILON_DECAY)
        
        # Calculate success rate
        recent_success = success_history[-50:]
        success_rate = sum(recent_success) / len(recent_success) if recent_success else 0.0

        if episode % 50 == 0:
            # Calculate session stats
            session_attempts = map_stats[map_idx]['attempts']
            session_goals = map_stats[map_idx]['goals']
            session_total_reward = map_stats[map_idx]['total_reward']
            
            map_sr_session = session_goals / session_attempts if session_attempts > 0 else 0.0
            map_avg_reward_session = session_total_reward / session_attempts if session_attempts > 0 else 0.0

        if episode % SAVE_INTERVAL == 0:
            agent.save(f"models/ddqn_submarine_ep{episode}.pth")
            
            # Save training state
            state_data = {
                'map1_history': map1_history,
                'map2_history': map2_history,
                'map3_history': map3_history
            }
            np.save("training_state.npy", state_data)

    agent.save("models/ddqn_submarine_final.pth")
    
    # Save final training state
    state_data = {
        'map1_history': map1_history,
        'map2_history': map2_history,
        'map3_history': map3_history
    }
    np.save("training_state.npy", state_data)
    
    print("\n" + "="*50)
    print("TRAINING COMPLETE - FINAL STATISTICS")
    print("="*50)
    print(f"{'Map File':<40} | {'Goals':<5} | {'Attempts':<8} | {'Success Rate':<12} | {'Avg Reward':<10}")
    print("-" * 85)
    
    for i, filename in enumerate(MAP_FILES):
        # Only show stats for maps that were actually used (if list was shortened)
        if i in map_stats and map_stats[i]['attempts'] > 0:
            stats = map_stats[i]
            goals = stats['goals']
            attempts = stats['attempts']
            avg_reward = stats['total_reward'] / attempts
            success_rate = (goals / attempts) * 100
            
            # Shorten filename for display
            display_name = filename.split('/')[-1]
            
            print(f"{display_name:<40} | {goals:<5} | {attempts:<8} | {success_rate:>6.1f}%      | {avg_reward:>8.1f}")
            
    print("="*50)
    
    # Save loss data
    if loss_history:
        np.save("training_loss.npy", np.array(loss_history))
        print("Network Training Loss saved to 'training_loss.npy'")
        
        avg_first_100 = sum(loss_history[:100]) / len(loss_history[:100]) if len(loss_history) >= 100 else 0
        avg_last_100 = sum(loss_history[-100:]) / len(loss_history[-100:]) if len(loss_history) >= 100 else 0
        peak_loss = max(loss_history)
        
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
