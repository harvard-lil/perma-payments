from werkzeug.exceptions import BadRequest

from django.shortcuts import render


def bad_request(request):
    context = {
        'heading': "400 Bad Request",
        'message': BadRequest.description
    }
    return render(request, 'generic.html', context, status=400)
