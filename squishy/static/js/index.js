// Client-side media library with pagination
document.addEventListener('DOMContentLoaded', function() {
    // State variables
    let allShows = [];
    let allMovies = [];
    let currentShowPage = 1;
    let currentMoviePage = 1;
    let totalShows = 0;
    let totalMovies = 0;
    let searchQuery = '';
    const ITEMS_PER_PAGE = 12; // Reduced to 12 items per page for better visibility
    
    // DOM Elements
    const searchInput = document.getElementById('searchInput');
    const searchButton = document.getElementById('searchButton');
    const clearSearchButton = document.getElementById('clearSearch');
    const searchLoader = document.getElementById('searchLoader');
    
    // Sections
    const initialEmptyState = document.getElementById('initialEmptyState');
    const globalEmptyState = document.getElementById('globalEmptyState');
    const showsSection = document.getElementById('showsSection');
    const moviesSection = document.getElementById('moviesSection');
    const showsEmptyState = document.getElementById('showsEmptyState');
    const moviesEmptyState = document.getElementById('moviesEmptyState');
    
    // Grids and stats
    const showsGrid = document.getElementById('showsGrid');
    const moviesGrid = document.getElementById('moviesGrid');
    const showsStats = document.getElementById('showsStats');
    const moviesStats = document.getElementById('moviesStats');
    
    // Pagination
    const showsPagination = document.getElementById('showsPagination');
    const moviesPagination = document.getElementById('moviesPagination');
    const showsPaginationInfo = document.getElementById('showsPaginationInfo');
    const moviesPaginationInfo = document.getElementById('moviesPaginationInfo');
    const showsPaginationControls = document.getElementById('showsPaginationControls');
    const moviesPaginationControls = document.getElementById('moviesPaginationControls');
    
    // Initialize - load all media
    loadMediaLibrary();
    
    // Event listeners
    searchButton.addEventListener('click', performSearch);
    clearSearchButton.addEventListener('click', clearSearch);
    searchInput.addEventListener('keyup', function(e) {
        if (e.key === 'Enter') {
            performSearch();
        }
    });
    
    // Load media library from API
    function loadMediaLibrary() {
        initialEmptyState.style.display = 'block';
        searchLoader.style.display = 'block';
        
        fetch('/api/paginated-media')
            .then(response => response.json())
            .then(data => {
                // Store data
                allShows = data.shows;
                allMovies = data.movies;
                totalShows = data.total_shows;
                totalMovies = data.total_movies;
                
                // Initial render
                renderLibrary();
                
                // Hide loader
                searchLoader.style.display = 'none';
                initialEmptyState.style.display = 'none';
            })
            .catch(error => {
                console.error('Error loading media library:', error);
                searchLoader.style.display = 'none';
                initialEmptyState.style.display = 'none';
                globalEmptyState.style.display = 'block';
            });
    }
    
    // Perform search
    function performSearch() {
        const query = searchInput.value.trim().toLowerCase();
        
        if (query === searchQuery) {
            return; // Same search, do nothing
        }
        
        searchQuery = query;
        
        // Show clear button if search is not empty
        if (searchQuery !== '') {
            clearSearchButton.style.display = 'inline-block';
        } else {
            clearSearchButton.style.display = 'none';
        }
        
        // Reset pagination
        currentShowPage = 1;
        currentMoviePage = 1;
        
        // Show loader
        searchLoader.style.display = 'block';
        
        // Fetch filtered data
        fetch(`/api/paginated-media?q=${encodeURIComponent(searchQuery)}`)
            .then(response => response.json())
            .then(data => {
                // Store data
                allShows = data.shows;
                allMovies = data.movies;
                totalShows = data.total_shows;
                totalMovies = data.total_movies;
                
                // Render
                renderLibrary();
                
                // Hide loader
                searchLoader.style.display = 'none';
            })
            .catch(error => {
                console.error('Error searching media library:', error);
                searchLoader.style.display = 'none';
            });
    }
    
    // Clear search
    function clearSearch() {
        searchInput.value = '';
        searchQuery = '';
        clearSearchButton.style.display = 'none';
        
        // Reset pagination
        currentShowPage = 1;
        currentMoviePage = 1;
        
        // Reload library
        loadMediaLibrary();
    }
    
    // Render the library with current pagination
    function renderLibrary() {
        // Handle empty library
        if (totalShows === 0 && totalMovies === 0) {
            showsSection.style.display = 'none';
            moviesSection.style.display = 'none';
            globalEmptyState.style.display = 'block';
            return;
        }
        
        globalEmptyState.style.display = 'none';
        
        // Render TV Shows
        renderShows();
        
        // Render Movies
        renderMovies();
    }
    
    // Render TV Shows section
    function renderShows() {
        if (totalShows === 0) {
            showsSection.style.display = 'block';
            showsEmptyState.style.display = 'block';
            showsGrid.style.display = 'none';
            showsPagination.style.display = 'none';
            showsStats.textContent = '0 shows found';
            return;
        }
        
        // Calculate pagination
        const totalShowPages = Math.ceil(totalShows / ITEMS_PER_PAGE);
        const startIdx = (currentShowPage - 1) * ITEMS_PER_PAGE;
        const endIdx = Math.min(startIdx + ITEMS_PER_PAGE, totalShows);
        const paginatedShows = allShows.slice(startIdx, endIdx);
        
        // Update stats
        showsStats.textContent = `${totalShows} show${totalShows !== 1 ? 's' : ''} found`;
        
        // Render shows grid
        showsGrid.innerHTML = '';
        
        paginatedShows.forEach(show => {
            const showCard = createShowCard(show);
            showsGrid.appendChild(showCard);
        });
        
        // Show sections
        showsSection.style.display = 'block';
        showsEmptyState.style.display = 'none';
        showsGrid.style.display = 'grid';
        
        // Render pagination if needed
        if (totalShowPages > 1) {
            showsPagination.style.display = 'flex';
            showsPaginationInfo.textContent = `Page ${currentShowPage} of ${totalShowPages}`;
            renderPaginationControls(showsPaginationControls, currentShowPage, totalShowPages, 'show');
        } else {
            showsPagination.style.display = 'none';
        }
    }
    
    // Render Movies section
    function renderMovies() {
        if (totalMovies === 0) {
            moviesSection.style.display = 'block';
            moviesEmptyState.style.display = 'block';
            moviesGrid.style.display = 'none';
            moviesPagination.style.display = 'none';
            moviesStats.textContent = '0 movies found';
            return;
        }
        
        // Calculate pagination
        const totalMoviePages = Math.ceil(totalMovies / ITEMS_PER_PAGE);
        const startIdx = (currentMoviePage - 1) * ITEMS_PER_PAGE;
        const endIdx = Math.min(startIdx + ITEMS_PER_PAGE, totalMovies);
        const paginatedMovies = allMovies.slice(startIdx, endIdx);
        
        // Update stats
        moviesStats.textContent = `${totalMovies} movie${totalMovies !== 1 ? 's' : ''} found`;
        
        // Render movies grid
        moviesGrid.innerHTML = '';
        
        paginatedMovies.forEach(movie => {
            const movieCard = createMovieCard(movie);
            moviesGrid.appendChild(movieCard);
        });
        
        // Show sections
        moviesSection.style.display = 'block';
        moviesEmptyState.style.display = 'none';
        moviesGrid.style.display = 'grid';
        
        // Render pagination if needed
        if (totalMoviePages > 1) {
            moviesPagination.style.display = 'flex';
            moviesPaginationInfo.textContent = `Page ${currentMoviePage} of ${totalMoviePages}`;
            renderPaginationControls(moviesPaginationControls, currentMoviePage, totalMoviePages, 'movie');
        } else {
            moviesPagination.style.display = 'none';
        }
    }
    
    // Create a TV Show card element
    function createShowCard(show) {
        const card = document.createElement('div');
        card.className = 'media-card';
        
        // Create link
        const link = document.createElement('a');
        link.href = `/shows/${show.id}`;
        
        // Create poster or placeholder
        if (show.poster_url) {
            const img = document.createElement('img');
            img.src = show.poster_url;
            img.alt = show.title;
            img.loading = 'lazy'; // Lazy load images
            link.appendChild(img);
        } else {
            const placeholder = document.createElement('div');
            placeholder.className = 'placeholder-poster';
            const initial = document.createElement('span');
            initial.textContent = show.title.charAt(0);
            placeholder.appendChild(initial);
            link.appendChild(placeholder);
        }
        
        // Create info div
        const info = document.createElement('div');
        info.className = 'media-info';
        
        // Add title
        const title = document.createElement('h3');
        title.textContent = show.display_name;
        info.appendChild(title);
        
        // Add type
        const type = document.createElement('span');
        type.className = 'media-type';
        type.textContent = 'TV Show';
        info.appendChild(type);
        
        // Add season count
        const count = document.createElement('span');
        count.className = 'media-count';
        count.textContent = `${show.season_count} season${show.season_count !== 1 ? 's' : ''}`;
        info.appendChild(count);
        
        link.appendChild(info);
        card.appendChild(link);
        
        return card;
    }
    
    // Create a Movie card element
    function createMovieCard(movie) {
        const card = document.createElement('div');
        card.className = 'media-card';
        
        // Create link
        const link = document.createElement('a');
        link.href = `/media/${movie.id}`;
        
        // Create poster or placeholder
        if (movie.poster_url) {
            const img = document.createElement('img');
            img.src = movie.poster_url;
            img.alt = movie.title;
            img.loading = 'lazy'; // Lazy load images
            link.appendChild(img);
        } else {
            const placeholder = document.createElement('div');
            placeholder.className = 'placeholder-poster';
            const initial = document.createElement('span');
            initial.textContent = movie.title.charAt(0);
            placeholder.appendChild(initial);
            link.appendChild(placeholder);
        }
        
        // Create info div
        const info = document.createElement('div');
        info.className = 'media-info';
        
        // Add title
        const title = document.createElement('h3');
        title.textContent = movie.display_name;
        info.appendChild(title);
        
        // Add type
        const type = document.createElement('span');
        type.className = 'media-type';
        type.textContent = 'Movie';
        info.appendChild(type);
        
        link.appendChild(info);
        card.appendChild(link);
        
        return card;
    }
    
    // Render pagination controls
    function renderPaginationControls(container, currentPage, totalPages, mediaType) {
        container.innerHTML = '';
        
        // Previous button
        if (currentPage > 1) {
            const prevButton = createPaginationButton('Previous', currentPage - 1, mediaType, 'pagination-prev');
            container.appendChild(prevButton);
        }
        
        // Page buttons
        const startPage = Math.max(1, currentPage - 2);
        const endPage = Math.min(totalPages, startPage + 4);
        
        for (let i = startPage; i <= endPage; i++) {
            const pageButton = createPaginationButton(i.toString(), i, mediaType, `pagination-page${i === currentPage ? ' active' : ''}`);
            container.appendChild(pageButton);
        }
        
        // Next button
        if (currentPage < totalPages) {
            const nextButton = createPaginationButton('Next', currentPage + 1, mediaType, 'pagination-next');
            container.appendChild(nextButton);
        }
    }
    
    // Create a pagination button
    function createPaginationButton(text, page, mediaType, className) {
        const button = document.createElement('a');
        button.href = 'javascript:void(0)';
        button.className = className;
        button.textContent = text;
        
        button.addEventListener('click', function() {
            if (mediaType === 'show') {
                currentShowPage = page;
                renderShows();
                // Scroll to shows section
                showsSection.scrollIntoView({ behavior: 'smooth' });
            } else if (mediaType === 'movie') {
                currentMoviePage = page;
                renderMovies();
                // Scroll to movies section
                moviesSection.scrollIntoView({ behavior: 'smooth' });
            }
        });
        
        return button;
    }
});