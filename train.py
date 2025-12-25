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
from src.ai.agent import DoubleDQNAgent, VanillaDQNAgent

# Configuration
WATCH_MODE = False
LOAD_MODEL = True     # IMPORTANT: Set to "True" to continue training from previous save
NUM_EPISODES = 2000
MAX_STEPS = 4000
BATCH_SIZE = 64
EPSILON_START = 0.2
EPSILON_END = 0.01
EPSILON_DECAY = 0.995
TARGET_UPDATE = 1000
SAVE_INTERVAL = 50

# Map configuration
MAP_FILES = [
    "src/cave_environment/map1_basic.csv",
    "src/cave_environment/map2_jagged.csv",
    "src/cave_environment/map3_jagged_long_narrow.csv",
    "src/cave_environment/map4_zigzag.csv"
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

def get_full_state(sonar_data, submarine):
    normalized_battery = submarine.battery / 500.0
    norm_vx = (submarine.vel_x + 7.0) / 14.0
    norm_vy = (submarine.vel_y + 7.0) / 14.0
    
    return np.concatenate([
        sonar_data,
        [normalized_battery],
        [norm_vx, norm_vy]
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

    spritesheet = SpriteSheet("src/cave_environment/tileset.png")
    
    # Initialize agent
    # Actions: up, down, left, right, glide (do nothing)
    agent = DoubleDQNAgent(input_shape=19, num_actions=5)
    epsilon = EPSILON_START
    episode_loss = np.full(NUM_EPISODES, None, dtype=np.float32)
    
    if LOAD_MODEL:
        try:
            agent.load("models/vanilla_dqn_submarine_final.pth")
            print("Successfully loaded existing model!")
            epsilon = EPSILON_START # Use the config value (0.2) instead of hardresetting to 1.0
        except Exception as e:
            print(f"Could not load model ({e}). This is expected if you upgraded the Network Architecture (Bigger Brain). Starting fresh!")
            epsilon = 1.0 # Reset exploration for new brain


    total_steps = 0

    print(f"Starting training on Device: {agent.device}")
    print("Press TAB to toggle Fast/Watch Mode. Press ESC to quit.")

    # Success tracking
    success_history = []
    loss_history = []
    map3_history = []
    map4_history = []
    map_stats = {
        i: {'goals': 0, 'attempts': 0, 'total_reward': 0} 
        for i in range(len(MAP_FILES))
    }
    
    start_episode = 0
    
    # Load training state if exists and we are loading model
    if LOAD_MODEL and os.path.exists("training_state.npy"):
        try:
            state_data = np.load("training_state.npy", allow_pickle=True).item()
            map3_history = state_data.get('map3_history', [])
            map4_history = state_data.get('map4_history', [])
            # We don't load epsilon to allow for restart if needed, 
            # but we will start lower than 1.0 if model is loaded.
            print(f"Loaded training state. Map 3 History: {len(map3_history)}, Map 4 History: {len(map4_history)}")
        except Exception as e:
            print(f"Error loading training state: {e}")

    for episode in range(start_episode, NUM_EPISODES):

        # Calculate sr
        recent_map3 = map3_history[-50:]
        map3_sr = sum(recent_map3) / len(recent_map3) if recent_map3 else 0.0
        
        recent_map4 = map4_history[-50:]
        map4_sr = sum(recent_map4) / len(recent_map4) if recent_map4 else 0.0

        # Base weights for map 1 & 2
        w1, w2 = 5.0, 5.0
        
        # Prioritize maps with lower success rates
        score3 = (1.1 - map3_sr) ** 2
        score4 = (1.1 - map4_sr) ** 2
        
        total_score = score3 + score4
        remaining_weight = 90.0
        
        w3 = (score3 / total_score) * remaining_weight
        w4 = (score4 / total_score) * remaining_weight
        
        weights = [w1, w2, w3, w4]
        
        # Select map based on dynamic weights
        map_idx = random.choices([0, 1, 2, 3], weights=weights, k=1)[0]
        
        map_stats[map_idx]['attempts'] += 1
        
        # Load environment & physics
        space, cave_env = load_level(map_idx, spritesheet)
        if not space:
            continue

        # Reset submarine
        start_x, start_y = 100, 300
        
        # below's for map 3 so it learns faster
        target_x_min = 50
        
        if map_idx == 2: # Map 3
            # Reverse curriculum: start near the end (2500), as mastery improves, push spawn back.
            if map3_sr > 0.8:
                target_x_min = 100
            elif map3_sr > 0.6:
                target_x_min = 1000
            elif map3_sr > 0.4:
                target_x_min = 1500
            elif map3_sr > 0.2:
                target_x_min = 2000
            else:
                target_x_min = 2500

            # Add variance to prevent overfitting to exact pixels
            target_x_min += random.randint(-50, 50)
            target_x_min = max(50, min(target_x_min, 2800))
            
        elif map_idx == 3: # Map 4
            # below's for map 4 so it learns faster
            if map4_sr > 0.8:
                target_x_min = 50      # Do the whole thing
            elif map4_sr > 0.7:
                target_x_min = 500
            elif map4_sr > 0.6:
                target_x_min = 900
            elif map4_sr > 0.5:
                target_x_min = 1200    # Do half
            elif map4_sr > 0.4:
                target_x_min = 1500
            elif map4_sr > 0.3:
                target_x_min = 1700
            elif map4_sr > 0.2:
                target_x_min = 1900
            else:
                target_x_min = 2100    # Just the end bit

            # Add variance
            target_x_min += random.randint(-50, 50)
            target_x_min = max(50, min(target_x_min, 2300))

        # safe start logic
        wall_rects = [t.rect for t in cave_env.environment_tiles]
        wall_rects.extend([o.rect for o in cave_env.obstacles])
        found_start = False
        
        for x in range(target_x_min, cave_env.environment_width - 50, 20):
             valid_ys = []
             # to prevent spawning in the ceiling/floor void for map 4 
             search_y_start = 200 if map_idx == 3 else 50
             search_y_end = 600 if map_idx == 3 else cave_env.environment_height - 50
             
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
            if map_idx == 3:
                start_x, start_y = 50, 400
            else:
                start_x, start_y = 100, 300

        submarine = Submarine(start_x, start_y)
        submarine.battery = 500
        
        sonar_body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
        sonar_body.position = (submarine.rect.centerx, submarine.rect.centery)
        space.add(sonar_body)
        sonar = Sonar(space, sonar_body)
        
        current_observation = sonar.get_observation()
        state = get_full_state(current_observation, submarine)
        
        total_reward = 0
        done = False
        display_hit_msg = False
        total_loss = 0.0
        for step in range(MAX_STEPS):
            # Event handling (Throttled in fast mode)
            if WATCH_MODE or step % 100 == 0:
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

            action = agent.select_action(state, epsilon)
            
            # Save previous position
            prev_x = submarine.true_x
            prev_y = submarine.true_y
            
            reward = -0.1 # Base penalty

            if action == 0: # Up
                submarine.move_up()
                reward += 0.5
            elif action == 1: # Down
                submarine.move_down()
                reward += 0.5
            elif action == 2: # Left
                submarine.move_left()
                reward -= 0.05
            elif action == 3: # Right
                submarine.move_right()
                reward += 0.5
            elif action == 4: # Glide
                # do nothing
                reward += 0.01
            
            submarine.update()
            sonar_body.position = (submarine.rect.centerx, submarine.rect.centery)
            
            # Check for battery pickups
            hits = pygame.sprite.spritecollide(submarine, cave_env.batteries, True)
            for hit in hits:
                submarine.battery += 20
                reward += 5 # Encourage collecting batteries
            
            next_observation = sonar.get_observation()
            next_state = get_full_state(next_observation, submarine)


            display_hit_msg = False
            
            hit_wall = False
            for reading in next_observation:
                if reading == 0: 
                    hit_wall = True
                    break
            
            if hit_wall:
                reward -= 2
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
                sonar_body.position = (submarine.rect.centerx, submarine.rect.centery)
            
            if submarine.rect.right >= cave_env.environment_width - 10:
                reward += 100
                reward += submarine.battery * 0.1 # Bonus for efficiency
                done = True
                success_history.append(1)
                if map_idx == 2: map3_history.append(1)
                if map_idx == 3: map4_history.append(1)
                map_stats[map_idx]['goals'] += 1

            if submarine.battery <= 0:
                reward -= 10
                done = True
                success_history.append(0)
                if map_idx == 2: map3_history.append(0)
                if map_idx == 3: map4_history.append(0)
            
            total_reward += reward

            agent.memory.push(state, action, reward, next_state, done)
            
            loss = agent.train_step(BATCH_SIZE)
            total_loss += loss if loss is not None else 0.0

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
        average_loss = total_loss / (step + 1)
        episode_loss[episode] = average_loss
        if episode % 10 == 0:
            print(f"Episode {episode}/{NUM_EPISODES} | Total Reward: {total_reward:.2f} | Epsilon: {epsilon:.2f} | Loss: {average_loss:.4f} ")

        if episode % SAVE_INTERVAL == 0:
            agent.save(f"models/vanilla_dqn_submarine_ep{episode}.pth")
        
        
        # Calculate success rate
        recent_success = success_history[-50:]
        success_rate = sum(recent_success) / len(recent_success) if recent_success else 0.0

        if episode % 50 == 0:
            m_stats = map_stats[map_idx]
            
            # Calculate rolling SR for the current map
            if map_idx == 2:
                recent = map3_history[-50:]
                map_sr_rolling = sum(recent) / len(recent) if recent else 0.0
            elif map_idx == 3:
                recent = map4_history[-50:]
                map_sr_rolling = sum(recent) / len(recent) if recent else 0.0
            else:
                # For maps 1/2 we don't track detailed history, fall back to lifetime
                map_sr_rolling = m_stats['goals'] / m_stats['attempts'] if m_stats['attempts'] > 0 else 0.0

            print(f"Ep {episode} (Map {map_idx + 1}) | Reward: {total_reward:.2f} | Eps: {epsilon:.2f} | SR (Rolling): {map_sr_rolling:.0%} | SR (Global 50): {success_rate:.0%}")


        if episode % SAVE_INTERVAL == 0:
            agent.save(f"models/ddqn_submarine_ep{episode}.pth")
            
            # Save training state
            state_data = {
                'map3_history': map3_history,
                'map4_history': map4_history
            }
            np.save("training_state.npy", state_data)

    np.save("models/vanilla_dqn_training_loss.npy", episode_loss)
    agent.save("models/vanilla_dqn_submarine_final.pth")
    
    # Save final training state
    state_data = {
        'map3_history': map3_history,
        'map4_history': map4_history
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
