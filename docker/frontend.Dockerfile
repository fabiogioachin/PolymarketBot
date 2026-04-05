FROM nginx:1.27-alpine

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy custom nginx config
COPY docker/nginx.conf /etc/nginx/conf.d/polymarket.conf

# Copy static assets (preserve /static/ prefix so HTML refs work)
COPY static/ /usr/share/nginx/html/static/
# Also serve index.html at root for /
COPY static/index.html /usr/share/nginx/html/index.html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
