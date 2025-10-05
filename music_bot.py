import discord
from discord.ext import commands
import yt_dlp as youtube_dl
import asyncio
from collections import deque
import os

# Konfigurasi
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Dictionary untuk menyimpan queue musik per guild
music_queues = {}

# Opsi untuk yt-dlp - optimasi untuk audio berkualitas
ytdl_opts = {
    'format': 'bestaudio[ext=m4a]/bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'extract_flat': 'in_playlist',
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'no_color': True,
    'noplaylist': True,
    'age_limit': None,
    'geo_bypass': True,
    'prefer_ffmpeg': True,
    'postprocessor_args': ['-ar', '48000'],
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'referer': 'https://www.youtube.com/',
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-us,en;q=0.5',
        'Sec-Fetch-Mode': 'navigate'
    }
}

ffmpeg_opts = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn -filter:a "volume=0.8" -b:a 192k -bufsize 512k',
    'executable': 'ffmpeg'
}

ytdl = youtube_dl.YoutubeDL(ytdl_opts)

class MusicQueue:
    def __init__(self):
        self.queue = deque()
        self.current = None
        
    def add(self, song):
        self.queue.append(song)
        
    def next(self):
        if self.queue:
            self.current = self.queue.popleft()
            return self.current
        self.current = None
        return None
        
    def clear(self):
        self.queue.clear()
        self.current = None

def get_queue(guild_id):
    if guild_id not in music_queues:
        music_queues[guild_id] = MusicQueue()
    return music_queues[guild_id]

@bot.event
async def on_ready():
    print(f'{bot.user} telah online!')
    print(f'Bot ID: {bot.user.id}')
    print('[INFO] Checking FFmpeg...')
    try:
        import subprocess
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
        print('[INFO] FFmpeg found!')
    except FileNotFoundError:
        print('[ERROR] FFmpeg not found! Please install FFmpeg.')

@bot.command(name='join', help='Bot bergabung ke voice channel')
async def join(ctx):
    if not ctx.author.voice:
        await ctx.send('❌ Kamu harus berada di voice channel!')
        return
    
    channel = ctx.author.voice.channel
    if ctx.voice_client is None:
        await channel.connect()
        await ctx.send(f'✅ Bergabung ke {channel.name}')
    else:
        await ctx.voice_client.move_to(channel)
        await ctx.send(f'✅ Pindah ke {channel.name}')

@bot.command(name='leave', help='Bot keluar dari voice channel')
async def leave(ctx):
    if ctx.voice_client:
        queue = get_queue(ctx.guild.id)
        queue.clear()
        await ctx.voice_client.disconnect()
        await ctx.send('👋 Keluar dari voice channel')
    else:
        await ctx.send('❌ Bot tidak berada di voice channel!')

def search_song(query, requester):
    """Function untuk mencari lagu di background thread"""
    try:
        data = ytdl.extract_info(f"ytsearch1:{query}", download=False)
        
        if 'entries' in data:
            data = data['entries'][0]
        
        # Format durasi dengan handling untuk float
        duration = data.get('duration', 0)
        if duration:
            duration = int(duration)
            duration_str = f"{duration // 60}:{duration % 60:02d}"
        else:
            duration_str = "Unknown"
        
        # Fallback untuk webpage_url
        webpage_url = data.get('webpage_url') or data.get('url') or f"https://youtube.com/watch?v={data.get('id', '')}"
        
        return {
            'url': data['url'],
            'title': data.get('title', 'Unknown Title'),
            'webpage_url': webpage_url,
            'duration': duration_str,
            'thumbnail': data.get('thumbnail', ''),
            'requester': requester  # Simpan info requester
        }
    except Exception as e:
        raise e

@bot.command(name='play', help='Putar musik dari YouTube')
async def play(ctx, *, query):
    if not ctx.author.voice:
        await ctx.send('❌ Kamu harus berada di voice channel!')
        return
    
    if ctx.voice_client is None:
        await ctx.author.voice.channel.connect()
    
    searching_msg = await ctx.send(f'🔍 Mencari: **{query}**...')
    await searching_msg.add_reaction('⏳')
    
    try:
        loop = asyncio.get_event_loop()
        # Pass requester info
        song = await loop.run_in_executor(None, search_song, query, ctx.author)
        
        queue = get_queue(ctx.guild.id)
        queue.add(song)
        
        await searching_msg.clear_reactions()
        await searching_msg.delete()
        
        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
            await play_next(ctx)
        else:
            embed = discord.Embed(
                title="➕ Ditambahkan ke Queue",
                description=f"**{song['title']}**",
                color=discord.Color.green()
            )
            embed.add_field(name="⏱️ Durasi", value=song['duration'], inline=True)
            embed.add_field(name="📍 Posisi", value=f"#{len(queue.queue)}", inline=True)
            embed.add_field(name="👤 Requested by", value=song['requester'].mention, inline=True)
            if song.get('thumbnail'):
                embed.set_thumbnail(url=song['thumbnail'])
            await ctx.send(embed=embed)
            
    except Exception as e:
        try:
            await searching_msg.clear_reactions()
            await searching_msg.delete()
        except:
            pass
        await ctx.send(f'❌ Terjadi kesalahan: {str(e)}')

async def play_next(ctx):
    queue = get_queue(ctx.guild.id)
    song = queue.next()
    
    if song is None:
        await ctx.send('✅ Queue selesai!')
        return
    
    try:
        print(f"[DEBUG] Re-extracting fresh URL for: {song['title']}")
        loop = asyncio.get_event_loop()
        
        def extract_url():
            data = ytdl.extract_info(song['webpage_url'], download=False)
            return data['url']
        
        fresh_url = await loop.run_in_executor(None, extract_url)
        print(f"[DEBUG] Fresh URL obtained, attempting to play...")
        
        player = discord.FFmpegPCMAudio(fresh_url, **ffmpeg_opts)
        
        def after_playing(error):
            if error:
                print(f'[ERROR] Playback error: {error}')
            else:
                print(f'[INFO] Finished playing: {song["title"]}')
            
            coro = play_next(ctx)
            fut = asyncio.run_coroutine_threadsafe(coro, bot.loop)
            try:
                fut.result()
            except Exception as e:
                print(f'[ERROR] Exception in after_playing: {e}')
        
        ctx.voice_client.play(player, after=after_playing)
        print(f"[INFO] Now playing: {song['title']}")
        
        # Embed dengan info requester
        embed = discord.Embed(
            title="🎵 Sedang Memutar",
            description=f"**{song['title']}**",
            color=discord.Color.blue(),
            url=song['webpage_url']
        )
        embed.add_field(name="⏱️ Durasi", value=song['duration'], inline=True)
        embed.add_field(name="📝 Sisa Queue", value=f"{len(queue.queue)} lagu", inline=True)
        embed.add_field(name="👤 Requested by", value=song['requester'].mention, inline=True)
        if song.get('thumbnail'):
            embed.set_thumbnail(url=song['thumbnail'])
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        print(f'[ERROR] Exception in play_next: {e}')
        await ctx.send(f'❌ Error saat memutar: {str(e)}')

@bot.command(name='pause', help='Jeda musik')
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send('⏸️ Musik dijeda')
    else:
        await ctx.send('❌ Tidak ada musik yang sedang diputar!')

@bot.command(name='resume', help='Lanjutkan musik')
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send('▶️ Musik dilanjutkan')
    else:
        await ctx.send('❌ Musik tidak sedang dijeda!')

@bot.command(name='skip', help='Skip ke lagu berikutnya')
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send('⏭️ Melewati lagu...')
    else:
        await ctx.send('❌ Tidak ada musik yang sedang diputar!')

@bot.command(name='stop', help='Hentikan musik dan bersihkan queue')
async def stop(ctx):
    if ctx.voice_client:
        queue = get_queue(ctx.guild.id)
        queue.clear()
        ctx.voice_client.stop()
        await ctx.send('⏹️ Musik dihentikan dan queue dibersihkan')
    else:
        await ctx.send('❌ Bot tidak berada di voice channel!')

@bot.command(name='queue', help='Lihat queue musik')
async def show_queue(ctx):
    queue = get_queue(ctx.guild.id)
    
    if queue.current is None and len(queue.queue) == 0:
        await ctx.send('📭 Queue kosong!')
        return
    
    embed = discord.Embed(
        title='📜 Queue Musik',
        color=discord.Color.purple()
    )
    
    if queue.current:
        embed.add_field(
            name='🎵 Sedang Diputar',
            value=f"**{queue.current['title']}**\n⏱️ Durasi: {queue.current['duration']}\n👤 By: {queue.current['requester'].mention}",
            inline=False
        )
    
    if queue.queue:
        queue_list = ""
        for i, song in enumerate(list(queue.queue)[:10], 1):
            queue_list += f"`{i}.` **{song['title']}** - `{song['duration']}`\n👤 {song['requester'].mention}\n"
        
        if len(queue.queue) > 10:
            queue_list += f"\n_...dan {len(queue.queue) - 10} lagu lainnya_"
        
        embed.add_field(name='📝 Selanjutnya', value=queue_list, inline=False)
    
    embed.set_footer(text=f"Total: {len(queue.queue)} lagu dalam queue")
    await ctx.send(embed=embed)

@bot.command(name='np', help='Lihat lagu yang sedang diputar')
async def now_playing(ctx):
    queue = get_queue(ctx.guild.id)
    
    if queue.current:
        embed = discord.Embed(
            title='🎵 Sedang Diputar',
            description=f"**{queue.current['title']}**",
            color=discord.Color.blue(),
            url=queue.current['webpage_url']
        )
        embed.add_field(name="⏱️ Durasi", value=queue.current['duration'], inline=True)
        embed.add_field(name="📝 Sisa Queue", value=f"{len(queue.queue)} lagu", inline=True)
        embed.add_field(name="👤 Requested by", value=queue.current['requester'].mention, inline=True)
        if queue.current.get('thumbnail'):
            embed.set_thumbnail(url=queue.current['thumbnail'])
        await ctx.send(embed=embed)
    else:
        await ctx.send('❌ Tidak ada musik yang sedang diputar!')

# Ganti dengan token bot Discord kamu
bot.run(os.getenv('MTQyMzk2MzAxNjIyMjk5ODU2MA.GooOF9.d4UAysS6tkqlB3P1Uht5CQtOnJnHsa7TXrPvqg'))